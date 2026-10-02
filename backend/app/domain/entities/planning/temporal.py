from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time, timedelta
from enum import Enum
import re


class DayOfWeek(str, Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"

    @classmethod
    def from_string(cls, value: str) -> DayOfWeek | None:
        clean = value.strip().lower()
        mapping = {
            "mon": cls.MONDAY,
            "monday": cls.MONDAY,
            "tue": cls.TUESDAY,
            "tues": cls.TUESDAY,
            "tuesday": cls.TUESDAY,
            "wed": cls.WEDNESDAY,
            "wednesday": cls.WEDNESDAY,
            "thu": cls.THURSDAY,
            "thur": cls.THURSDAY,
            "thurs": cls.THURSDAY,
            "thursday": cls.THURSDAY,
            "fri": cls.FRIDAY,
            "friday": cls.FRIDAY,
            "sat": cls.SATURDAY,
            "saturday": cls.SATURDAY,
            "sun": cls.SUNDAY,
            "sunday": cls.SUNDAY,
        }
        return mapping.get(clean)


ALL_DAYS = (
    DayOfWeek.MONDAY,
    DayOfWeek.TUESDAY,
    DayOfWeek.WEDNESDAY,
    DayOfWeek.THURSDAY,
    DayOfWeek.FRIDAY,
    DayOfWeek.SATURDAY,
    DayOfWeek.SUNDAY,
)


@dataclass(frozen=True)
class TimeRange:
    """A contiguous window of opening hours."""

    start: time
    end: time

    def contains(self, t: time) -> bool:
        if self.start <= self.end:
            return self.start <= t <= self.end
        # Overnight range, e.g. 20:00 to 02:00
        return t >= self.start or t <= self.end

    def can_accommodate(self, start_t: time, duration_minutes: int | None = None) -> bool:
        if not self.contains(start_t):
            return False
        if duration_minutes is None:
            return True

        # Calculate expected end time
        total_start_mins = start_t.hour * 60 + start_t.minute
        total_end_mins = total_start_mins + duration_minutes

        if self.start <= self.end:
            range_end_mins = self.end.hour * 60 + self.end.minute
            return total_end_mins <= range_end_mins
        else:
            # Overnight range
            range_end_mins = (self.end.hour + 24) * 60 + self.end.minute
            if start_t < self.start:
                total_start_mins += 24 * 60
                total_end_mins += 24 * 60
            return total_end_mins <= range_end_mins


@dataclass(frozen=True)
class DaySchedule:
    """Opening schedule for a specific day of the week."""

    is_closed: bool = False
    is_24h: bool = False
    ranges: tuple[TimeRange, ...] = ()

    def can_accommodate(self, start_t: time, duration_minutes: int | None = None) -> bool:
        if self.is_closed:
            return False
        if self.is_24h:
            return True
        return any(r.can_accommodate(start_t, duration_minutes) for r in self.ranges)

    def is_open_at_all(self) -> bool:
        return not self.is_closed and (self.is_24h or len(self.ranges) > 0)

    def next_available_start(self, current_time: time, duration_minutes: int | None = None) -> time | None:
        """Find the earliest start time at or after current_time that accommodates the visit."""
        if self.is_closed:
            return None
        if self.is_24h or self.can_accommodate(current_time, duration_minutes):
            return current_time
        # Check upcoming ranges on the same day
        for r in self.ranges:
            if r.start >= current_time and r.can_accommodate(r.start, duration_minutes):
                return r.start
        return None

    def can_accommodate_window(
        self, start_t: time, end_t: time, duration_minutes: int | None = None
    ) -> bool:
        """Check if any operating range allows a complete visit between start_t and end_t."""
        if self.is_closed:
            return False
        if self.is_24h:
            return True
        dur = duration_minutes or 60
        limit_mins = end_t.hour * 60 + end_t.minute
        for r in self.ranges:
            earliest = max(r.start, start_t) if r.start <= r.end else r.start
            earliest_mins = earliest.hour * 60 + earliest.minute
            if earliest_mins > limit_mins:
                continue
            if earliest_mins + dur <= limit_mins and r.can_accommodate(earliest, dur):
                return True
        return False


@dataclass(frozen=True)
class OpeningHoursSchedule:
    """Weekly opening schedule domain entity.

    Answers can_accommodate(day, start_time, duration) -> bool | None.
    Distinguishes unknown (None) from closed (False).
    """

    is_unknown: bool = False
    days: dict[DayOfWeek, DaySchedule] = field(default_factory=dict)

    def can_accommodate(
        self,
        day_str: str | None,
        start_t: time | str | None,
        duration_minutes: int | None = None,
    ) -> bool | None:
        """Returns True if open/can accommodate, False if closed, None if unknown."""
        if self.is_unknown:
            return None

        if not day_str:
            # No specific day requested: if every day is closed, False; otherwise None (uncertain)
            if self.days and all(ds.is_closed for ds in self.days.values()):
                return False
            return None

        day = DayOfWeek.from_string(day_str)
        if day is None or day not in self.days:
            return None

        schedule = self.days[day]
        if schedule.is_closed:
            return False

        if start_t is None:
            # If no time given, check whether it is open at all on that day
            return schedule.is_open_at_all()

        parsed_time = _to_time(start_t)
        if parsed_time is None:
            return None

        return schedule.can_accommodate(parsed_time, duration_minutes)

    def can_accommodate_window(
        self,
        day_str: str | None,
        start_t: time | str | None,
        end_t: time | str | None,
        duration_minutes: int | None = None,
    ) -> bool | None:
        """Checks if a visit fits anywhere within a time window (e.g. afternoon to evening)."""
        if self.is_unknown:
            return None

        if not day_str:
            if self.days and all(ds.is_closed for ds in self.days.values()):
                return False
            return None

        day = DayOfWeek.from_string(day_str)
        if day is None or day not in self.days:
            return None

        schedule = self.days[day]
        if schedule.is_closed:
            return False

        if start_t is None or end_t is None:
            return schedule.is_open_at_all()

        parsed_start = _to_time(start_t)
        parsed_end = _to_time(end_t)
        if parsed_start is None or parsed_end is None:
            return schedule.is_open_at_all()

        return schedule.can_accommodate_window(parsed_start, parsed_end, duration_minutes)

    def next_available_start(
        self,
        day_str: str | None,
        current_time: time | str,
        duration_minutes: int | None = None,
    ) -> time | None:
        """Finds next opening time on the requested day at or after current_time."""
        if self.is_unknown or not day_str:
            return None
        day = DayOfWeek.from_string(day_str)
        if day is None or day not in self.days:
            return None
        parsed_time = _to_time(current_time)
        if parsed_time is None:
            return None
        return self.days[day].next_available_start(parsed_time, duration_minutes)


def _to_time(val: time | str | None) -> time | None:
    if val is None:
        return None
    if isinstance(val, time):
        return val
    try:
        parts = val.strip().split(":")
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _parse_time(time_str: str) -> time | None:
    time_str = time_str.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not match:
        return None
    h, m = int(match.group(1)), int(match.group(2))
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    return None


def _parse_time_ranges(ranges_str: str) -> tuple[TimeRange, ...]:
    """Parses one or more ranges like '08:00-18:00' or '12:30-14:00 & 18:00-22:30'."""
    chunks = re.split(r"&|,", ranges_str)
    result: list[TimeRange] = []
    for chunk in chunks:
        chunk = chunk.strip()
        m = re.match(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", chunk)
        if m:
            t1 = _parse_time(m.group(1))
            t2 = _parse_time(m.group(2))
            if t1 and t2:
                result.append(TimeRange(start=t1, end=t2))
    return tuple(result)


def _get_day_span(start_day: DayOfWeek, end_day: DayOfWeek) -> list[DayOfWeek]:
    days = list(ALL_DAYS)
    i1 = days.index(start_day)
    i2 = days.index(end_day)
    if i1 <= i2:
        return days[i1 : i2 + 1]
    return days[i1:] + days[: i2 + 1]


def parse_opening_hours(hours_str: str | None) -> OpeningHoursSchedule:
    """Parses real-world opening hours strings into a structured OpeningHoursSchedule.

    Never fabricates missing hours. Returns is_unknown=True for unlisted/unparseable values.
    """
    if not hours_str or not hours_str.strip():
        return OpeningHoursSchedule(is_unknown=True)

    text = hours_str.strip()
    lower = text.lower()

    # 1. 24 hours
    if "24 hours" in lower or "24/7" in lower or "open 24" in lower:
        return OpeningHoursSchedule(
            is_unknown=False,
            days={d: DaySchedule(is_24h=True) for d in ALL_DAYS},
        )

    # 2. "Daily HH:MM-HH:MM"
    m_daily = re.match(r"^daily\s+(\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2})$", text, re.IGNORECASE)
    if m_daily:
        ranges = _parse_time_ranges(m_daily.group(1))
        if ranges:
            return OpeningHoursSchedule(
                is_unknown=False,
                days={d: DaySchedule(ranges=ranges) for d in ALL_DAYS},
            )

    # 3. Multi-clause schedules, e.g.:
    # "Mon-Sat 07:00-18:00, Sun 08:00-16:00"
    # "Tue-Sun 10:00-18:00"
    # "Tue-Sat 12:30-14:00 & 18:00-22:30"
    clauses = [c.strip() for c in text.split(",") if c.strip()]
    day_map: dict[DayOfWeek, DaySchedule] = {}

    parsed_any = False
    for clause in clauses:
        # Match e.g. "Mon-Sat 09:00-16:00" or "Tue-Sat 12:30-14:00 & 18:00-22:30"
        m_range = re.match(
            r"^([a-zA-Z]+)\s*[-–]\s*([a-zA-Z]+)\s+((?:\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}(?:\s*&\s*\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2})?)|24 hours)$",
            clause,
            re.IGNORECASE,
        )
        if m_range:
            d1 = DayOfWeek.from_string(m_range.group(1))
            d2 = DayOfWeek.from_string(m_range.group(2))
            range_content = m_range.group(3)
            if d1 and d2:
                span = _get_day_span(d1, d2)
                if "24 hours" in range_content.lower():
                    for d in span:
                        day_map[d] = DaySchedule(is_24h=True)
                else:
                    ranges = _parse_time_ranges(range_content)
                    if ranges:
                        for d in span:
                            day_map[d] = DaySchedule(ranges=ranges)
                parsed_any = True
                continue

        # Match single day clause: "Sun 08:00-16:00" or "Monday closed"
        m_single = re.match(
            r"^([a-zA-Z]+)\s+((?:\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}(?:\s*&\s*\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2})?)|closed|24 hours)$",
            clause,
            re.IGNORECASE,
        )
        if m_single:
            d = DayOfWeek.from_string(m_single.group(1))
            val = m_single.group(2).lower()
            if d:
                if val == "closed":
                    day_map[d] = DaySchedule(is_closed=True)
                elif "24 hours" in val:
                    day_map[d] = DaySchedule(is_24h=True)
                else:
                    ranges = _parse_time_ranges(m_single.group(2))
                    if ranges:
                        day_map[d] = DaySchedule(ranges=ranges)
                parsed_any = True
                continue

    if not parsed_any:
        # Fallback to unknown rather than guessing
        return OpeningHoursSchedule(is_unknown=True)

    # Any days not listed in a partial schedule (e.g. "Tue-Sun" implies Mon closed)
    for d in ALL_DAYS:
        if d not in day_map:
            day_map[d] = DaySchedule(is_closed=True)

    return OpeningHoursSchedule(is_unknown=False, days=day_map)
