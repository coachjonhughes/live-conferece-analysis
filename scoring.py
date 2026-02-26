"""
scoring.py - All analytical layers:
  1. Current actual score
  2. Optimistic ceiling (mathematical elimination)
  3. Seed-based projection
  4. Leverage index
  5. Win probability via Monte Carlo
  6. Scenario builder (seeds hold / best case / worst case per team)
"""

import random
import logging
from collections import defaultdict
from typing import Optional

from data_model import (
    MeetState, MeetEvent, TeamScore, Gender, EventStatus, RoundType
)
from config import PLACE_POINTS, MONTE_CARLO_ITERATIONS
from scraper import _mark_to_seconds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed ordering helpers
# ---------------------------------------------------------------------------

def _seed_sort_key(entry, event: MeetEvent) -> float:
    """
    Return a float for sorting entries by seed quality.
    Lower = better for track events (faster time).
    Higher = better for field events (longer/higher mark).
    Returns a large float so unseedable athletes go to the back.
    """
    mark = entry.effective_seed or ""
    val = _mark_to_seconds(mark)
    if val is None:
        return 1e9

    name = event.base_event_name.lower()
    # Field events stored as negative in _mark_to_seconds → bigger magnitude = better
    field_keywords = ["jump", "vault", "throw", "shot", "weight", "discus", "javelin", "hammer"]
    if any(k in name for k in field_keywords):
        return -val   # reverse: larger mark is better (less negative after flip)
    return val        # track: smaller time is better


def _rank_entries_by_seed(event: MeetEvent) -> list:
    """Return entries sorted best→worst by effective seed mark."""
    entries = [e for e in event.entries if e.athlete.name]
    return sorted(entries, key=lambda e: _seed_sort_key(e, event))


# ---------------------------------------------------------------------------
# 1. Current actual score
# ---------------------------------------------------------------------------

def compute_actual_scores(state: MeetState, gender: Gender) -> dict[str, TeamScore]:
    """Tally points from all completed finals only."""
    scores: dict[str, TeamScore] = {}

    def _get_or_create(team: str) -> TeamScore:
        if team not in scores:
            scores[team] = TeamScore(team=team, gender=gender)
        return scores[team]

    # Regular finals
    for event in state.get_completed_finals(gender):
        # Group athletes by final_place to detect ties
        from collections import defaultdict as _dd
        place_groups = _dd(list)
        for entry in event.entries:
            a = entry.athlete
            if a.final_place and a.final_place in PLACE_POINTS:
                place_groups[a.final_place].append(a)

        for place, athletes_at_place in place_groups.items():
            n = len(athletes_at_place)
            # Split points across tied places: e.g. 2 tied for 3rd get (6+5)/2=5.5 each
            total_pts = sum(PLACE_POINTS.get(place + i, 0) for i in range(n))
            split_pts = total_pts / n
            for a in athletes_at_place:
                ts = _get_or_create(a.team)
                ts.actual_points += split_pts
                ts.events_scored.append(f"{event.event_name} ({place}{'+' if n > 1 else ''}={split_pts:.2f}pt)")

    # Combined events (Pent/Hep) if complete
    for combined in state.combined_events:
        if combined.gender != gender or not combined.is_complete:
            continue
        for a in combined.athletes:
            if a.final_place and a.final_place in PLACE_POINTS:
                pts = PLACE_POINTS[a.final_place]
                ts = _get_or_create(a.team)
                ts.actual_points += pts
                ts.events_scored.append(f"{combined.event_name} ({a.final_place})")

    return scores


# ---------------------------------------------------------------------------
# Helper: get realistic finalist entries for an upcoming final
# ---------------------------------------------------------------------------

def _get_finalist_entries(event: MeetEvent, state: MeetState, gender: Gender,
                           n_finalists: int = 8) -> list:
    """
    Returns the entries to use for projection/ceiling/Monte Carlo for an upcoming final.

    Rules:
    - If the final already has entries (post-prelim), use them as-is.
    - If the final has no entries but a prelim exists, take only the top-N seeds
      from the prelim (default 8) — these are the projected finalists.
    - Field events have no prelims, so all entries are used directly.
    """
    entries = event.entries

    if not entries:
        # Look for a paired prelim
        for other in state.events:
            if (other.gender == gender
                    and other.event_code == event.event_code
                    and other.round_type == RoundType.PRELIM
                    and other.entries):
                entries = other.entries
                break

    if not entries:
        return []

    # If entries came from a prelim (more than n_finalists), trim to top seeds
    if len(entries) > n_finalists:
        ranked = sorted(
            entries,
            key=lambda e: _seed_sort_key(e, event)
        )
        entries = ranked[:n_finalists]

    return entries


# ---------------------------------------------------------------------------
# 2. Optimistic ceiling
# ---------------------------------------------------------------------------

def compute_optimistic_ceiling(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict[str, int]:
    """
    For each team: actual points + maximum possible from remaining finals.
    Assumes each team's athletes finish as high as possible without conflicting
    with each other (if two athletes from same team, they take spots 1 and 2, etc.)
    Does NOT deduct from other teams.
    """
    ceilings: dict[str, int] = defaultdict(int)

    # Start from actual
    all_teams = set()
    for event in state.events:
        for entry in event.entries:
            if entry.athlete.team:
                all_teams.add(entry.athlete.team)

    for team in all_teams:
        base = actual.get(team, TeamScore(team=team, gender=gender)).actual_points
        ceilings[team] = base

    # Upcoming finals
    for event in state.get_upcoming_finals(gender):
        # Use top-8 seeds only (realistic finalists)
        entries = _get_finalist_entries(event, state, gender)
        if not entries:
            continue

        # Count entries per team
        team_athletes: dict[str, int] = defaultdict(int)
        for entry in entries:
            team_athletes[entry.athlete.team] += 1

        # Ceiling: for each team independently, assume their athletes take the
        # best N consecutive spots starting from 1 (where N = their athlete count).
        # This is per-team optimistic — not a shared competition for spots.
        for team, count in team_athletes.items():
            team_pts = sum(PLACE_POINTS.get(p, 0) for p in range(1, min(count + 1, 9)))
            ceilings[team] += team_pts

    return dict(ceilings)


# ---------------------------------------------------------------------------
# 3. Seed-based projection
# ---------------------------------------------------------------------------

def compute_seed_projection(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict[str, int]:
    """
    Rank athletes in each upcoming final by their effective seed mark.
    Assign points by projected finish position.
    Handles ties by splitting points (average of tied places).
    """
    projections: dict[str, int] = defaultdict(int)

    for team, ts in actual.items():
        projections[team] = ts.actual_points

    for event in state.get_upcoming_finals(gender):
        # Use top-8 seeds only as projected finalists
        finalist_entries = _get_finalist_entries(event, state, gender)
        if not finalist_entries:
            continue
        # Temporarily substitute entries for ranking
        orig_entries = event.entries
        event.entries = finalist_entries
        ranked = _rank_entries_by_seed(event)
        event.entries = orig_entries

        # Check for ties (same mark)
        place = 1
        i = 0
        while i < len(ranked) and place <= 8:
            # Find group of tied entries
            j = i + 1
            current_key = _seed_sort_key(ranked[i], event)
            while j < len(ranked) and abs(_seed_sort_key(ranked[j], event) - current_key) < 0.001:
                j += 1

            tied_count = j - i
            tied_places = list(range(place, min(place + tied_count, 9)))
            avg_pts = sum(PLACE_POINTS.get(p, 0) for p in tied_places) / len(tied_places) if tied_places else 0

            for entry in ranked[i:j]:
                if any(PLACE_POINTS.get(p, 0) > 0 for p in tied_places):
                    projections[entry.athlete.team] = projections.get(entry.athlete.team, 0) + avg_pts

            place += tied_count
            i = j

    return dict(projections)


# ---------------------------------------------------------------------------
# 4. Leverage index
# ---------------------------------------------------------------------------

def compute_leverage_index(
    state: MeetState,
    gender: Gender,
    actual: dict[str, TeamScore]
) -> list[dict]:
    """
    For each remaining final, calculate:
    - max_swing: max possible point difference between 1st and 2nd place teams
      if one team dominates vs another team dominates
    - spread: how many different teams have athletes entered (diversity = uncertainty)
    - headline: human-readable string for social media

    Returns list sorted by leverage (highest first).
    """
    results = []

    # Current top 2 teams by actual score
    sorted_teams = sorted(actual.items(), key=lambda x: x[1].actual_points, reverse=True)
    top_teams = [t for t, _ in sorted_teams[:5]] if sorted_teams else []

    for event in state.get_upcoming_finals(gender):
        if not event.entries:
            continue

        teams_in_event = list({e.athlete.team for e in event.entries})
        n_teams = len(teams_in_event)

        # Max swing = if top contender wins all scoring spots vs if rival does
        # Simple approximation: difference between a team winning 1st vs finishing last
        max_pts_available = sum(PLACE_POINTS.get(p, 0) for p in range(1, min(9, len(event.entries) + 1)))
        max_swing = PLACE_POINTS.get(1, 10) - PLACE_POINTS.get(min(8, len(event.entries)), 0)

        # How many top-5 teams have entries?
        top_teams_in_event = [t for t in top_teams if t in teams_in_event]
        contention_score = len(top_teams_in_event) * max_swing

        # Points still available total
        athletes_scoring = min(8, len(event.entries))
        total_pts = sum(PLACE_POINTS.get(p, 0) for p in range(1, athletes_scoring + 1))

        results.append({
            "event_name": event.event_name,
            "event": event,
            "leverage_score": contention_score,
            "max_swing": max_swing,
            "total_pts_available": total_pts,
            "n_teams": n_teams,
            "top_teams_in_event": top_teams_in_event,
            "headline": _leverage_headline(event, top_teams_in_event, total_pts, max_swing),
        })

    return sorted(results, key=lambda x: x["leverage_score"], reverse=True)


def _leverage_headline(event, top_teams, total_pts, max_swing) -> str:
    teams_str = " & ".join(top_teams[:2]) if top_teams else "multiple teams"
    return (
        f"{event.event_name}: {total_pts} pts available — "
        f"{teams_str} both have athletes entered. "
        f"Max swing: {max_swing} pts between contenders."
    )


# ---------------------------------------------------------------------------
# 5. Monte Carlo win probability
# ---------------------------------------------------------------------------

# Event-type-specific probability that the top seed wins.
# Derived from NCAA D1 championship data:
#   - Sprints (60m, 200m): top seed wins ~42% in loaded fields
#   - 400m: ~38% (more tactical)
#   - Hurdles: ~45%
#   - 800m/mile: ~30% (more variable, tactical)
#   - 3000m/5000m: ~35%
#   - Field events: ~40%
#   - Relay: ~40%
# We model each athlete's win probability using a Plackett-Luce model:
# P(athlete i wins) ∝ strength_i, where strength_i derived from seed rank.

def _get_top_seed_win_prob(event: MeetEvent) -> float:
    name = event.base_event_name.lower()
    if "60m" in name and "hurdle" not in name:
        return 0.42
    elif "200m" in name:
        return 0.40
    elif "400m" in name:
        return 0.38
    elif "hurdle" in name:
        return 0.45
    elif "800m" in name:
        return 0.30
    elif "mile" in name or "1000m" in name:
        return 0.30
    elif "3000m" in name or "5000m" in name:
        return 0.35
    elif "relay" in name:
        return 0.40
    else:
        return 0.40  # field events


def _seed_rank_to_strength(rank: int, n_athletes: int, top_seed_prob: float) -> float:
    """
    Convert seed rank (1 = best) to a relative strength weight using
    an exponential decay model calibrated to top_seed_prob.
    """
    if n_athletes <= 1:
        return 1.0
    # Decay rate calibrated so that rank-1 athlete has ~top_seed_prob of winning
    # when summed over all athletes
    decay = 0.65
    raw = decay ** (rank - 1)
    return raw


def compute_win_probability(
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender,
    n_iterations: int = MONTE_CARLO_ITERATIONS
) -> dict[str, float]:
    """
    Monte Carlo simulation of remaining events.
    Returns probability dict: team → probability of winning the meet.
    """
    # Upcoming finals — use top-8 projected finalists for each event
    upcoming = state.get_upcoming_finals(gender)

    if not upcoming:
        # If no events left, just check who's winning
        if not actual:
            return {}
        max_pts = max(ts.actual_points for ts in actual.values())
        winners = [t for t, ts in actual.items() if ts.actual_points == max_pts]
        return {t: (1.0 / len(winners) if t in winners else 0.0) for t in actual}

    # Precompute ranked entries and strengths for each upcoming event
    event_data = []
    for event in upcoming:
        # Monte Carlo uses top 15 seeds — wider field captures upset probability
        finalist_entries = _get_finalist_entries(event, state, gender, n_finalists=15)
        if not finalist_entries:
            continue
        orig_entries = event.entries
        event.entries = finalist_entries
        ranked = _rank_entries_by_seed(event)
        event.entries = orig_entries
        n = len(ranked)
        top_prob = _get_top_seed_win_prob(event)
        strengths = [_seed_rank_to_strength(i + 1, n, top_prob) for i in range(n)]
        total_strength = sum(strengths)
        probs = [s / total_strength for s in strengths]
        event_data.append((event, ranked, probs))

    win_counts: dict[str, int] = defaultdict(int)
    all_teams = set(actual.keys())
    for ed in event_data:
        for entry in ed[1]:
            all_teams.add(entry.athlete.team)

    for _ in range(n_iterations):
        sim_scores: dict[str, float] = {t: actual.get(t, TeamScore(team=t, gender=gender)).actual_points
                                        for t in all_teams}

        for event, ranked, probs in event_data:
            # Simulate finishing order using Plackett-Luce sampling
            remaining_entries = list(zip(ranked, probs))
            remaining_total = sum(p for _, p in remaining_entries)

            place = 1
            while remaining_entries and place <= 8:
                # Normalize probabilities
                total = sum(p for _, p in remaining_entries)
                if total <= 0:
                    break
                r = random.random() * total
                cumulative = 0
                chosen_idx = 0
                for idx, (entry, p) in enumerate(remaining_entries):
                    cumulative += p
                    if r <= cumulative:
                        chosen_idx = idx
                        break

                winner_entry, _ = remaining_entries.pop(chosen_idx)
                pts = PLACE_POINTS.get(place, 0)
                if pts > 0:
                    sim_scores[winner_entry.athlete.team] = sim_scores.get(winner_entry.athlete.team, 0) + pts

                place += 1

        max_score = max(sim_scores.values()) if sim_scores else 0
        leaders = [t for t, s in sim_scores.items() if s == max_score]
        for t in leaders:
            win_counts[t] += 1.0 / len(leaders)

    total = sum(win_counts.values())
    return {t: win_counts[t] / total for t in all_teams if win_counts.get(t, 0) > 0}


# ---------------------------------------------------------------------------
# 6. Scenario builder for a specific team
# ---------------------------------------------------------------------------

def compute_team_scenarios(
    team: str,
    actual: dict[str, TeamScore],
    state: MeetState,
    gender: Gender
) -> dict:
    """
    For a specific team, compute three scenarios:
    A) Seeds hold exactly — everyone finishes per seed rank
    B) Best case — team's athletes finish as high as possible
    C) Worst case — team's athletes finish as low as possible (just out of points = 9th)
    
    Returns dict with scenario scores and event-by-event breakdown.
    """
    base_pts = actual.get(team, TeamScore(team=team, gender=gender)).actual_points

    scenario_a = base_pts  # seeds hold
    scenario_b = base_pts  # best case
    scenario_c = base_pts  # worst case
    event_breakdown = []

    for event in state.get_upcoming_finals(gender):
        # Use same top-8 finalist entries as projection/ceiling
        finalist_entries = _get_finalist_entries(event, state, gender)
        if not finalist_entries:
            continue

        # Filter to this team's athletes among the finalists
        team_entries = [e for e in finalist_entries if e.athlete.team == team]
        if not team_entries:
            continue

        # Rank all finalists by seed — use athlete name as key (not id, which is fragile)
        ranked = sorted(finalist_entries, key=lambda e: _seed_sort_key(e, event))
        rank_map = {e.athlete.name: i + 1 for i, e in enumerate(ranked)}

        # Scenario A: seeds hold — use same tie-splitting logic as compute_seed_projection
        # Group all finalists by seed value, split points among tied athletes
        a_pts = 0
        entry_details = []

        # Build tie-aware place/points map (same algorithm as compute_seed_projection)
        tie_pts_map: dict[str, float] = {}
        place = 1
        i = 0
        while i < len(ranked) and place <= 8:
            j = i + 1
            current_key = _seed_sort_key(ranked[i], event)
            while j < len(ranked) and abs(_seed_sort_key(ranked[j], event) - current_key) < 0.001:
                j += 1
            tied_count = j - i
            tied_places = list(range(place, min(place + tied_count, 9)))
            avg_pts = sum(PLACE_POINTS.get(p, 0) for p in tied_places) / len(tied_places) if tied_places else 0
            for e in ranked[i:j]:
                tie_pts_map[e.athlete.name] = avg_pts
            place += tied_count
            i = j

        for entry in team_entries:
            pts = tie_pts_map.get(entry.athlete.name, 0)
            proj_place = rank_map.get(entry.athlete.name, 9)
            a_pts += pts
            entry_details.append({
                "athlete": entry.athlete.name,
                "seed_mark": entry.effective_seed or "N/A",
                "proj_place": proj_place,
                "seed_pts": pts,
            })

        # Scenario B: best case — team's athletes take best consecutive spots
        # (same logic as ceiling: independent per-team optimistic)
        b_pts = sum(PLACE_POINTS.get(p, 0) for p in range(1, min(len(team_entries) + 1, 9)))

        # Scenario C: worst case — all athletes finish 9th or lower (0 pts)
        c_pts = 0

        scenario_a += a_pts
        scenario_b += b_pts
        scenario_c += c_pts

        event_breakdown.append({
            "event": event.event_name,
            "athletes": entry_details,
            "scenario_a_pts": a_pts,
            "scenario_b_pts": b_pts,
            "scenario_c_pts": c_pts,
        })

    return {
        "team": team,
        "current": base_pts,
        "scenario_a": scenario_a,   # Seeds hold
        "scenario_b": scenario_b,   # Best case
        "scenario_c": scenario_c,   # Worst case
        "breakdown": event_breakdown,
    }


# ---------------------------------------------------------------------------
# Master function — run all layers at once
# ---------------------------------------------------------------------------

def run_all_analysis(state: MeetState, gender: Gender) -> dict:
    """Run all scoring layers and return a combined results dict."""
    actual = compute_actual_scores(state, gender)
    ceilings = compute_optimistic_ceiling(actual, state, gender)
    projections = compute_seed_projection(actual, state, gender)
    leverage = compute_leverage_index(state, gender, actual)
    win_probs = compute_win_probability(actual, state, gender)

    # All teams seen across all layers
    all_teams = set(actual.keys()) | set(ceilings.keys()) | set(projections.keys())

    team_scores = []
    for team in sorted(all_teams):
        ts = actual.get(team, TeamScore(team=team, gender=gender))
        ts.optimistic_ceiling = ceilings.get(team, ts.actual_points)
        ts.seed_projection = int(projections.get(team, ts.actual_points))
        ts.win_probability = round(win_probs.get(team, 0.0) * 100, 1)
        team_scores.append(ts)

    # Sort by projected score descending
    team_scores.sort(key=lambda x: x.seed_projection, reverse=True)

    return {
        "gender": gender,
        "team_scores": team_scores,
        "leverage_index": leverage[:8],  # top 8 highest leverage events
        "actual": actual,
        "state": state,
    }
