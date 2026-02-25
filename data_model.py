"""
data_model.py - Dataclasses representing all meet entities.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Gender(str, Enum):
    WOMEN = "Women"
    MEN = "Men"


class RoundType(str, Enum):
    PRELIM = "Prelims"
    FINAL = "Final"
    COMBINED_EVENT = "CombinedEvent"  # pent/hep sub-events


class EventStatus(str, Enum):
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    FINAL = "Final"


@dataclass
class Athlete:
    name: str
    team: str
    seed_mark: Optional[str] = None        # Season best from start list
    prelim_mark: Optional[str] = None      # Actual prelim result (sprints use this as seed)
    final_mark: Optional[str] = None       # Actual final result
    final_place: Optional[int] = None      # 1-8 (None if DNF/DNS/DQ or >8th)
    points_scored: int = 0


@dataclass
class EventEntry:
    """One athlete's entry in a specific event."""
    athlete: Athlete
    effective_seed: Optional[str] = None   # The mark used for projection logic
    projected_place: Optional[int] = None  # Assigned during projection analysis


@dataclass
class MeetEvent:
    event_name: str          # e.g. "Women 200m"
    gender: Gender
    round_type: RoundType
    status: EventStatus
    event_code: str          # e.g. "002"
    round_num: int           # 1 = first round, 2 = final round
    compiled_url: str        # full URL to compiled/result page
    start_url: str           # full URL to start list
    day: str                 # "Thursday" / "Friday" / "Saturday"
    start_time: str          # "5:00 PM"

    # Populated after scraping
    entries: list[EventEntry] = field(default_factory=list)

    # The corresponding final event (set during pairing step)
    final_event: Optional["MeetEvent"] = None
    prelim_event: Optional["MeetEvent"] = None

    @property
    def is_scoreable(self) -> bool:
        """Only finals count toward team score."""
        return self.round_type == RoundType.FINAL and self.status == EventStatus.FINAL

    @property
    def base_event_name(self) -> str:
        """Strip gender prefix for matching: 'Women 200m' → '200m'."""
        return self.event_name.replace("Women ", "").replace("Men ", "").strip()

    @property
    def is_sprint_event(self) -> bool:
        name = self.base_event_name.lower()
        return any(s in name for s in ["60m", "200m", "400m", "60m hurdles"])


@dataclass
class CombinedEventResult:
    """Final standings for Pentathlon or Heptathlon."""
    event_name: str    # "Pentathlon" or "Heptathlon"
    gender: Gender
    status: EventStatus
    scores_url: str
    athletes: list[Athlete] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.status == EventStatus.FINAL and bool(self.athletes)


@dataclass
class TeamScore:
    team: str
    gender: Gender
    actual_points: int = 0
    events_scored: list[str] = field(default_factory=list)

    # Projection fields (populated by scoring.py)
    optimistic_ceiling: int = 0
    seed_projection: int = 0
    win_probability: float = 0.0

    # Scenario builder outputs
    scenario_seeds_hold: int = 0
    scenario_best_case: int = 0
    scenario_worst_case: int = 0


@dataclass
class MeetState:
    """Full snapshot of the meet at a given scrape time."""
    meet_url: str
    meet_name: str
    last_scraped: str           # ISO timestamp
    events: list[MeetEvent] = field(default_factory=list)
    combined_events: list[CombinedEventResult] = field(default_factory=list)

    # Previously seen final events — used to detect NEW finals for email trigger
    previously_final: set[str] = field(default_factory=set)

    def get_events_by_gender(self, gender: Gender) -> list[MeetEvent]:
        return [e for e in self.events if e.gender == gender]

    def get_completed_finals(self, gender: Gender) -> list[MeetEvent]:
        return [e for e in self.events
                if e.gender == gender and e.is_scoreable]

    def get_upcoming_finals(self, gender: Gender) -> list[MeetEvent]:
        """Finals not yet completed — includes ones with start lists posted."""
        return [e for e in self.events
                if e.gender == gender
                and e.round_type == RoundType.FINAL
                and e.status != EventStatus.FINAL]
