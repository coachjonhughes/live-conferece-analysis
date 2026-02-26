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
    # Pentathlon is always Women, Heptathlon is always Men
    if "pentathlon" in name_lower and "heptathlon" not in name_lower:
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

    FlashResults index tables have this structure:
      Day | Time | (blank) | Event Name (link OR plain text) | Round | Start List link | Result link | (blank) | Status

    The event name may be a plain text cell OR a link depending on meet year.
    We must NOT use the Result/Start List link text as the event name.
    """
    url = f"{meet_url}/index.htm"
    soup = _get(url)
    if not soup:
        raise RuntimeError(f"Could not fetch meet index: {url}")

    events = []
    title_tag = soup.find("title")
    meet_name = title_tag.get_text(strip=True) if title_tag else "Track Meet"
    current_day = "Unknown"

    # Words that indicate a cell is a column label, not an event name
    NON_EVENT_TEXTS = {
        "result", "results", "scores", "start list", "status",
        "day", "start", "rnd", "round", "", "-"
    }
    EVENT_KEYWORDS = [
        "women", "men", "mile", "hurdle", "relay", "jump",
        "vault", "shot", "weight", "throw", "dmr", "pentathlon",
        "heptathlon", "3000", "5000", "800m", "400m", "200m",
        "60m", "1500", "1000",
    ]

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if not cells or len(cells) < 4:
            continue

        texts = [c.get_text(strip=True) for c in cells]

        if texts[0] in ("Thursday", "Friday", "Saturday"):
            current_day = texts[0]

        compiled_href = None
        start_href = None
        round_str = ""
        start_time = ""
        event_name = ""

        for i, cell in enumerate(cells):
            cell_text = texts[i] if i < len(texts) else ""
            links = cell.find_all("a")

            # Round detection
            clean = cell_text.strip().rstrip("s")
            if clean in ("Prelim", "Final"):
                round_str = clean

            # Time detection
            if re.match(r"\d+:\d+ [AP]M", cell_text):
                start_time = cell_text

            # Event name: cell text that looks like an event name (not a link label)
            if (cell_text.lower() not in NON_EVENT_TEXTS
                    and any(kw in cell_text.lower() for kw in EVENT_KEYWORDS)
                    and not event_name):
                event_name = cell_text

            for link in links:
                href = link.get("href", "")
                link_text = link.get_text(strip=True)

                # Event name from link — only if it looks like an actual event name
                if (link_text.lower() not in NON_EVENT_TEXTS
                        and any(kw in link_text.lower() for kw in EVENT_KEYWORDS)
                        and not event_name):
                    event_name = link_text

                if "_compiled.htm" in href:
                    compiled_href = href
                elif "_start.htm" in href:
                    start_href = href
                elif "_Scores.htm" in href:
                    compiled_href = href
                    start_href = href

        # Only add if we found a compiled URL
        # Event name fallback: derive from compiled href if still empty
        if compiled_href:
            if not event_name:
                # Will be resolved from page title during individual page fetch
                event_name = ""
            events.append({
                "event_name": event_name,
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

def _split_athlete_team(raw: str) -> tuple[str, str]:
    """
    FlashResults merges athlete name and team into one cell, e.g.:
        'Kaila JACKSONGeorgia [JR]'   -> ('Kaila JACKSON', 'Georgia')
        'Brianna LYSTONLSU [JR]'      -> ('Brianna LYSTON', 'LSU')
        'Jordan ANTHONYArkansas [JR]' -> ('Jordan ANTHONY', 'Arkansas')

    Strategy:
    1. Strip year tag [JR]/[SR]/[FR]/[SO]
    2. Check for known all-caps team names (LSU, TCU, etc.) at end
    3. Otherwise find where LASTNAME caps block ends and TitleCase team begins
    """
    raw = _normalize_mark(raw)
    raw = re.sub(r'\s*\[(?:JR|SR|FR|SO|\d+)\]\s*$', '', raw, flags=re.IGNORECASE).strip()

    if not raw:
        return "", ""

    # Known all-caps team names in SEC and major conferences
    ALL_CAPS_TEAMS = [
        'LSU', 'TCU', 'SMU', 'UAB', 'UTSA', 'UTEP', 'UCF', 'BYU',
        'VCU', 'UNLV', 'UNC', 'USC', 'UCLA', 'UCONN', 'USF', 'FIU',
        'FAU', 'UMBC', 'NJIT', 'UMass',
        # NOTE: 'URI' intentionally excluded — it is a suffix of 'Missouri'
        # which causes 'MissouRI' to be incorrectly split as team='URI'
    ]
    for team in ALL_CAPS_TEAMS:
        if raw.upper().endswith(team.upper()):
            name_part = raw[:-len(team)].strip()
            if name_part:
                return name_part, team

    # Standard case: LASTNAME followed immediately by TitleCase team name
    match = re.search(r'([A-Z]{2,})((?:[A-Z][a-z].*))$', raw)
    if match:
        team_part = match.group(2).strip()
        name_part = raw[:match.start(2)].strip()
        return name_part, team_part

    return raw, ""


def _parse_result_page(soup: BeautifulSoup, is_start_list: bool = False) -> tuple[list[Athlete], EventStatus]:
    """
    Parse a compiled result or start list page.
    Returns (list of Athlete, EventStatus).

    FlashResults actual column structure (from diagnostic):
      Results:   Pl | (blank) | Athlete+Team | Time | ... | SB/PB flag
      StartList: (blank) | Ln | (blank) | Athlete+Team | SB | NCAA | PB
    """
    athletes = []
    status = EventStatus.SCHEDULED

    if not soup:
        return athletes, status

    tables = soup.find_all("table")

    # Collect athletes across all matching tables (heats are separate tables)
    all_found_athletes = []
    all_has_places = False

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        # Must contain "athlete" or "team" column
        is_relay_table = "team" in header_texts and "athlete" not in header_texts
        if "athlete" not in header_texts and not is_relay_table:
            continue

        # Skip the records table — it has "Athlete" but no "Pl" or "Time" column
        has_results_cols = any(h in header_texts for h in ("pl", "time", "sb", "ln", "ht"))
        if not has_results_cols:
            continue

        # Identify column indices
        athlete_idx = place_idx = mark_idx = seed_idx = lane_idx = heat_idx = None
        for i, h in enumerate(header_texts):
            if h == "athlete" or (is_relay_table and h == "team"):
                athlete_idx = i
            elif h in ("pl", "place"):
                place_idx = i
            elif h in ("time", "mark", "distance", "height"):
                mark_idx = i
            elif h == "sb":
                seed_idx = i
            elif h in ("ln", "lane"):
                lane_idx = i
            elif h == "ht":
                heat_idx = i

        if athlete_idx is None:
            continue

        # If no mark column found, use the cell immediately after athlete
        if mark_idx is None and not is_start_list:
            mark_idx = athlete_idx + 1

        has_places = False
        found_athletes = []

        # 2026 FlashResults start lists have malformed HTML:
        # <tbody> contains <td> elements directly (not wrapped in <tr>)
        # BeautifulSoup only finds the header <tr>, data cells are loose
        # Fix: collect all <td> from tbody and group them by column count
        tbody = table.find("tbody")
        data_rows = []
        if tbody:
            loose_tds = tbody.find_all("td", recursive=False)
            if loose_tds:
                # Group loose <td> elements into rows based on header column count
                ncols = len(header_texts)
                grouped = [loose_tds[i:i+ncols] for i in range(0, len(loose_tds), ncols)]
                data_rows = grouped
            else:
                # Normal structure: rows in tbody
                data_rows = [r.find_all(["td","th"]) for r in tbody.find_all("tr")]
        else:
            data_rows = [r.find_all(["td","th"]) for r in rows[1:]]

        for cells in data_rows:
            if not cells or len(cells) <= athlete_idx:
                continue

            def ct(idx):
                if idx is None or idx >= len(cells):
                    return ""
                return _normalize_mark(cells[idx].get_text(strip=True))

            raw_athlete = ct(athlete_idx)
            if not raw_athlete or raw_athlete.lower() in ("athlete", "name", ""):
                continue

            # Relay table: Team column cell contains "<b> GEORGIA</b><small>Georgia </small>"
            # Read team name from <small> tag which has the proper-case version
            if is_relay_table:
                cell = cells[athlete_idx]
                small = cell.find("small")
                team = small.get_text(strip=True) if small else raw_athlete.title()
                # Normalize LSU which is all-caps in small tag too
                if team.upper() == "LSU":
                    team = "LSU"
                name = f"{team} Relay"
            else:
                # Split merged athlete+team cell (individual events)
                name, team = _split_athlete_team(raw_athlete)

            if not name or not team:
                continue

            # Place
            place_str = ct(place_idx) if place_idx is not None else ""
            # Also check cell 0 if place_idx not found (often "Pl" is col 0)
            if not place_str and place_idx is None:
                place_str = ct(0)
            place = None
            if place_str.isdigit():
                place = int(place_str)
                if 1 <= place <= 8:
                    has_places = True

            # Mark/time
            mark = ct(mark_idx) if mark_idx is not None else ""
            # Strip parenthetical splits like "6.56(6.554)"
            mark = re.sub(r'\(.*?\)', '', mark).strip()

            # Seed mark
            seed = ct(seed_idx) if seed_idx is not None else ""
            # Normalize seed — remove flag like "=SB", "PB", "SB"
            seed = re.sub(r'^[=]?(SB|PB|MR|CR|FR|NR|WR)$', '', seed, flags=re.IGNORECASE).strip()

            athlete = Athlete(
                name=name,
                team=team,
                seed_mark=seed or None,
                final_mark=mark if not is_start_list else None,
                final_place=place,
            )
            found_athletes.append(athlete)

        if found_athletes:
            all_found_athletes.extend(found_athletes)
            if has_places:
                all_has_places = True

    # Determine status from all collected athletes
    if all_found_athletes:
        athletes = all_found_athletes
        if all_has_places or (not is_start_list and any(a.final_mark for a in athletes)):
            status = EventStatus.FINAL
        elif not is_start_list:
            status = EventStatus.IN_PROGRESS
        else:
            status = EventStatus.SCHEDULED

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

        if name_idx is None:
            continue

        athletes = []
        has_final = False

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells or name_idx >= len(cells):
                continue

            def ct(idx):
                if idx is None or idx >= len(cells):
                    return ""
                return _normalize_mark(cells[idx].get_text(strip=True))

            raw_name = ct(name_idx)
            if not raw_name:
                continue

            # Handle both merged (name+team in one cell) and separate columns
            if team_idx is not None:
                name = raw_name
                team = ct(team_idx)
            else:
                # Merged cell — same logic as regular result parser
                name, team = _split_athlete_team(raw_name)

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

        # If event name is blank (2025 index style), read it from page title
        # Page titles look like: "Women 60 M", "Men 1 Mile", etc.
        if not raw["event_name"] and soup:
            title_tag = soup.find("title")
            if title_tag:
                page_title = title_tag.get_text(strip=True)
                # Clean up suffixes like " - SEC Indoor Championships"
                page_title = page_title.split(" - ")[0].strip()
                # Normalize "60 M" -> "60m", "1 Mile" -> "1 Mile" etc
                raw["event_name"] = page_title
                event.event_name = page_title
                gender = _infer_gender(page_title)
                event.gender = gender

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
