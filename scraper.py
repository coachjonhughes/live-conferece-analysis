"""
scraper.py - Fetches and parses FlashResults meet pages using requests + BeautifulSoup.
No browser automation needed — FlashResults serves static HTML.
"""

import re
import time
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from data_model import (
    MeetEvent, MeetState, CombinedEventResult,
    Athlete, EventEntry, Gender, RoundType, EventStatus
)
from config import COMBINED_EVENT_PREFIXES

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_DELAY = 0.5   # seconds between requests — be polite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """Fetch a URL and return parsed BeautifulSoup, or None on failure."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            logger.warning(f"HTTP {resp.status_code} for {url}")
        except requests.RequestException as e:
            logger.warning(f"Request failed ({attempt+1}/{retries}): {e}")
            time.sleep(2 ** attempt)
    return None


def _infer_gender(event_name: str) -> Gender:
    name_lower = event_name.lower()
    if "women" in name_lower:
        return Gender.WOMEN
    return Gender.MEN


def _infer_round(round_str: str) -> RoundType:
    s = round_str.lower()
    if "prelim" in s:
        return RoundType.PRELIM
    return RoundType.FINAL


def _normalize_mark(mark: str) -> str:
    """Clean whitespace and common artifacts from mark strings."""
    return mark.strip().replace("\xa0", "").replace("  ", " ")


def _mark_to_seconds(mark: str) -> Optional[float]:
    """
    Convert a time mark string to seconds for sorting/comparison.
    Handles: 6.54, 45.23, 1:45.23, 13-04.50 (field), 5.85m (field).
    Returns None if unparseable (field events or DNS/DNF/DQ).
    """
    mark = _normalize_mark(mark).upper()
    if mark in ("DNS", "DNF", "DQ", "NH", "NM", "FOUL", ""):
        return None
    # Remove trailing letters like 'm', 'w' wind indicators in parentheses
    mark = re.sub(r"\s*\(.*\)", "", mark)
    mark = re.sub(r"[a-zA-Z]$", "", mark).strip()

    # Field event: feet-inches like 13-04.50 → not a time, return large number for sort
    if re.match(r"^\d+-\d+", mark):
        try:
            parts = mark.split("-")
            feet = float(parts[0])
            inches = float(parts[1])
            return -(feet * 12 + inches)   # negative so larger mark = lower sort value
        except Exception:
            return None

    # Metric field: 16.45 (no colon, no dash) — treat as negative for "bigger is better"
    # We detect these heuristically: if no colon and value < 200 it might be a field mark
    # For our purposes we only need relative ordering within an event so this is fine

    # Time: MM:SS.ss or SS.ss
    try:
        if ":" in mark:
            parts = mark.split(":")
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        else:
            return float(mark)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Index page parser
# ---------------------------------------------------------------------------

def parse_index(meet_url: str) -> list[dict]:
    """
    Parse the meet index page and return a list of raw event dicts.
    Each dict has: event_name, round_str, compiled_url, start_url, day, start_time
    """
    url = f"{meet_url}/index.htm"
    soup = _get(url)
    if not soup:
        raise RuntimeError(f"Could not fetch meet index: {url}")

    events = []

    # Detect meet name
    title_tag = soup.find("title")
    meet_name = title_tag.get_text(strip=True) if title_tag else "Track Meet"

    current_day = "Unknown"

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if not cells or len(cells) < 6:
            continue

        texts = [c.get_text(strip=True) for c in cells]

        # Day header rows have "Thursday"/"Friday"/"Saturday" in first cell
        if texts[0] in ("Thursday", "Friday", "Saturday"):
            current_day = texts[0]

        # Event rows: look for a link in the event name cell
        event_link = None
        compiled_href = None
        start_href = None
        round_str = ""
        start_time = ""

        for i, cell in enumerate(cells):
            links = cell.find_all("a")
            cell_text = texts[i] if i < len(texts) else ""

            # The round cell contains "Prelims", "Final", "Finals"
            if cell_text in ("Prelims", "Final", "Finals", "Finals "):
                round_str = cell_text.strip().rstrip("s")  # normalize to "Prelim"/"Final"

            # Time cell
            if re.match(r"\d+:\d+ [AP]M", cell_text):
                start_time = cell_text

            for link in links:
                href = link.get("href", "")
                if "_compiled.htm" in href:
                    compiled_href = href
                    event_link = link.get_text(strip=True)
                elif "_start.htm" in href:
                    start_href = href
                elif "_Scores.htm" in href:
                    compiled_href = href
                    start_href = href
                    event_link = link.get_text(strip=True)

        if event_link and compiled_href:
            events.append({
                "event_name": event_link,
                "round_str": round_str or "Final",
                "compiled_url": f"{meet_url}/{compiled_href}",
                "start_url": f"{meet_url}/{start_href}" if start_href else "",
                "day": current_day,
                "start_time": start_time,
                "compiled_href": compiled_href,
            })

    return events, meet_name


# ---------------------------------------------------------------------------
# Determine event code and round number from href
# ---------------------------------------------------------------------------

def _parse_href(href: str) -> tuple[str, int, bool]:
    """
    '002-1_compiled.htm' → ('002', 1, False)
    '017_Scores.htm'     → ('017', 0, True)
    """
    basename = href.split("/")[-1]
    scores_match = re.match(r"(\d+)_Scores\.htm", basename)
    if scores_match:
        return scores_match.group(1), 0, True

    match = re.match(r"(\d+)-(\d+)_", basename)
    if match:
        return match.group(1), int(match.group(2)), False

    return "000", 1, False


# ---------------------------------------------------------------------------
# Result / start list page parser
# ---------------------------------------------------------------------------

def _parse_result_page(soup: BeautifulSoup, is_start_list: bool = False) -> tuple[list[Athlete], EventStatus]:
    """
    Parse a compiled result or start list page.
    Returns (list of Athlete, EventStatus).

    FlashResults compiled pages contain a table with columns like:
    Place | Name | Year | Team | Time/Mark | [Wind] | [SB/PB]
    
    Start list pages have:
    # | Name | Year | Team | SB
    """
    athletes = []
    status = EventStatus.SCHEDULED

    if not soup:
        return athletes, status

    # Look for the main results table — FlashResults uses consistent structure
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Check header row to identify column positions
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        # Must have name and team columns
        if "name" not in header_texts and "athlete" not in header_texts:
            continue

        # Identify column indices
        name_idx = team_idx = mark_idx = place_idx = seed_idx = None
        for i, h in enumerate(header_texts):
            if h in ("name", "athlete"):
                name_idx = i
            elif h in ("team", "school", "affiliation"):
                team_idx = i
            elif h in ("time", "mark", "result", "distance", "height"):
                mark_idx = i
            elif h in ("pl", "place", "#", "pos"):
                place_idx = i
            elif h in ("sb", "seed", "entry", "pb", "best"):
                seed_idx = i

        if name_idx is None or team_idx is None:
            continue

        has_places = False

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(filter(None, [name_idx, team_idx])):
                continue

            def cell_text(idx):
                if idx is None or idx >= len(cells):
                    return ""
                return _normalize_mark(cells[idx].get_text(strip=True))

            name = cell_text(name_idx)
            team = cell_text(team_idx)

            if not name or not team:
                continue
            # Skip header-like rows
            if name.lower() in ("name", "athlete", ""):
                continue

            mark = cell_text(mark_idx) if mark_idx is not None else ""
            seed = cell_text(seed_idx) if seed_idx is not None else ""

            place_str = cell_text(place_idx) if place_idx is not None else ""
            place = None
            if place_str.isdigit():
                place = int(place_str)
                if 1 <= place <= 8:
                    has_places = True

            athlete = Athlete(
                name=name,
                team=team,
                seed_mark=seed or None,
                final_mark=mark if not is_start_list else None,
                final_place=place,
            )
            athletes.append(athlete)

        if athletes:
            if has_places or (not is_start_list and any(a.final_mark for a in athletes)):
                status = EventStatus.FINAL
            elif not is_start_list:
                status = EventStatus.IN_PROGRESS
            else:
                status = EventStatus.SCHEDULED
            break   # Found the right table

    return athletes, status


# ---------------------------------------------------------------------------
# Combined event (Pent/Hep) scores page parser
# ---------------------------------------------------------------------------

def _parse_scores_page(soup: BeautifulSoup, event_name: str, gender: Gender) -> CombinedEventResult:
    """Parse a _Scores.htm page for Pentathlon or Heptathlon final standings."""
    result = CombinedEventResult(
        event_name=event_name,
        gender=gender,
        status=EventStatus.SCHEDULED,
        scores_url="",
    )

    if not soup:
        return result

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        if "name" not in header_texts and "athlete" not in header_texts:
            continue

        name_idx = team_idx = place_idx = score_idx = None
        for i, h in enumerate(header_texts):
            if h in ("name", "athlete"):
                name_idx = i
            elif h in ("team", "school"):
                team_idx = i
            elif h in ("pl", "place", "#"):
                place_idx = i
            elif h in ("pts", "points", "score", "total"):
                score_idx = i

        if name_idx is None or team_idx is None:
            continue

        athletes = []
        has_final = False

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(filter(None, [name_idx, team_idx])):
                continue

            def ct(idx):
                if idx is None or idx >= len(cells):
                    return ""
                return _normalize_mark(cells[idx].get_text(strip=True))

            name = ct(name_idx)
            team = ct(team_idx)
            if not name or not team:
                continue

            place_str = ct(place_idx)
            place = int(place_str) if place_str.isdigit() else None
            if place and place <= 8:
                has_final = True

            a = Athlete(name=name, team=team, final_place=place)
            athletes.append(a)

        if athletes:
            result.athletes = athletes
            result.status = EventStatus.FINAL if has_final else EventStatus.IN_PROGRESS
            break

    return result


# ---------------------------------------------------------------------------
# Main scrape entry point
# ---------------------------------------------------------------------------

def scrape_meet(meet_url: str) -> MeetState:
    """
    Full scrape of a FlashResults meet.
    Returns a MeetState with all events populated.
    """
    logger.info(f"Scraping meet: {meet_url}")

    raw_events, meet_name = parse_index(meet_url)

    state = MeetState(
        meet_url=meet_url,
        meet_name=meet_name,
        last_scraped=datetime.now().isoformat(),
    )

    # Track combined events separately
    combined_codes_seen = set()

    for raw in raw_events:
        href = raw["compiled_href"]
        event_code, round_num, is_scores = _parse_href(href)

        gender = _infer_gender(raw["event_name"])
        round_type = _infer_round(raw["round_str"])

        # Handle Pent/Hep scores pages
        if is_scores and event_code in COMBINED_EVENT_PREFIXES:
            if event_code not in combined_codes_seen:
                combined_codes_seen.add(event_code)
                time.sleep(REQUEST_DELAY)
                soup = _get(raw["compiled_url"])
                combined = _parse_scores_page(soup, raw["event_name"], gender)
                combined.scores_url = raw["compiled_url"]
                state.combined_events.append(combined)
            continue

        # Skip combined event sub-events (pent/hep individual disciplines)
        if event_code in COMBINED_EVENT_PREFIXES:
            continue

        # Build the MeetEvent shell
        event = MeetEvent(
            event_name=raw["event_name"],
            gender=gender,
            round_type=round_type,
            status=EventStatus.SCHEDULED,
            event_code=event_code,
            round_num=round_num,
            compiled_url=raw["compiled_url"],
            start_url=raw["start_url"],
            day=raw["day"],
            start_time=raw["start_time"],
        )

        # Fetch the compiled page to get status and results
        time.sleep(REQUEST_DELAY)
        soup = _get(raw["compiled_url"])
        athletes, status = _parse_result_page(soup, is_start_list=False)

        # If compiled page has no results yet, try the start list for seeds
        if status == EventStatus.SCHEDULED and raw["start_url"]:
            time.sleep(REQUEST_DELAY)
            start_soup = _get(raw["start_url"])
            start_athletes, _ = _parse_result_page(start_soup, is_start_list=True)
            athletes = start_athletes

        event.status = status
        event.entries = [EventEntry(athlete=a, effective_seed=a.seed_mark) for a in athletes]

        state.events.append(event)

    # Pair prelim events with their finals
    _pair_prelim_final(state)

    # Set effective seeds based on event type rules
    _assign_effective_seeds(state)

    logger.info(f"Scrape complete: {len(state.events)} events, "
                f"{len(state.combined_events)} combined events")
    return state


# ---------------------------------------------------------------------------
# Prelim → Final pairing
# ---------------------------------------------------------------------------

def _pair_prelim_final(state: MeetState):
    """
    Match prelim events (round 1) with their corresponding final (round 2)
    by event_code. Store cross-references.
    """
    by_code: dict[str, list[MeetEvent]] = {}
    for event in state.events:
        by_code.setdefault(event.event_code, []).append(event)

    for code, evs in by_code.items():
        prelim = next((e for e in evs if e.round_num == 1 and e.round_type == RoundType.PRELIM), None)
        final = next((e for e in evs if e.round_num == 2 or e.round_type == RoundType.FINAL), None)
        if prelim and final:
            prelim.final_event = final
            final.prelim_event = prelim

            # Copy prelim results onto each athlete found in the final
            if prelim.status == EventStatus.FINAL:
                prelim_by_name = {e.athlete.name: e.athlete for e in prelim.entries}
                for entry in final.entries:
                    prelim_athlete = prelim_by_name.get(entry.athlete.name)
                    if prelim_athlete:
                        entry.athlete.prelim_mark = prelim_athlete.final_mark


def _assign_effective_seeds(state: MeetState):
    """
    Apply seeding logic per event type:
    - 60m, 200m, 400m, 60m Hurdles (sprint finals): use prelim mark
    - 800m and above: use season best from start list
    - Field events: use season best
    - Relay: use team seed mark
    """
    for event in state.events:
        if event.round_type != RoundType.FINAL:
            continue
        for entry in event.entries:
            a = entry.athlete
            if event.is_sprint_event:
                # Use prelim time if available, fall back to seed
                entry.effective_seed = a.prelim_mark or a.seed_mark
            else:
                entry.effective_seed = a.seed_mark
