from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone, tzinfo
import re

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

MONTH_PATTERN = re.compile(
    r"\b(?:in\s+)?("
    + "|".join(MONTHS.keys())
    + r")(?:\s+(\d{4}))?\b",
    flags=re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def extract_time_range(
    text: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    ref_now = now or datetime.now(tz=timezone.utc)
    lowered = text.lower()

    # Only the first ISO date is used. Multi-date ranges like "from 2025-06-01
    # to 2025-06-30" are not yet supported and will return a single-day window
    # for the first date found.
    for pattern in DATE_PATTERN.finditer(text):
        year, month, day = (int(group) for group in pattern.groups())
        start = datetime(year, month, day, tzinfo=ref_now.tzinfo)
        return (start, start + timedelta(days=1))

    if "today" in lowered:
        return _day_range(ref_now)
    if "yesterday" in lowered:
        return _day_range(ref_now - timedelta(days=1))
    if "last week" in lowered:
        return _week_range(ref_now - timedelta(days=7))
    if "this week" in lowered:
        return _week_range(ref_now)
    if "last month" in lowered:
        year = ref_now.year if ref_now.month > 1 else ref_now.year - 1
        month = ref_now.month - 1 or 12
        return _month_range(year, month, tz=ref_now.tzinfo)
    if "this month" in lowered:
        return _month_range(ref_now.year, ref_now.month, tz=ref_now.tzinfo)

    month_match = MONTH_PATTERN.search(lowered)
    if month_match:
        month_name, year_text = month_match.groups()
        year = int(year_text) if year_text else ref_now.year
        month = MONTHS[month_name]
        return _month_range(year, month, tz=ref_now.tzinfo)
    return None


def temporal_overlap_score(
    occurred_from: datetime | None,
    occurred_to: datetime | None,
    query_range: tuple[datetime, datetime] | None,
) -> float:
    """Score how much a record's occurrence window overlaps with a query range.

    Both the record and query ranges use half-open interval semantics: [start, end).
    A record whose occurred_from equals the query_end is considered outside the range.
    """
    if query_range is None or occurred_from is None:
        return 0.0
    query_start, query_end = query_range
    record_end = occurred_to or occurred_from
    if record_end <= query_start or occurred_from >= query_end:
        return 0.0
    overlap_start = max(occurred_from, query_start)
    overlap_end = min(record_end, query_end)
    overlap_seconds = max((overlap_end - overlap_start).total_seconds(), 0.0)
    if overlap_seconds <= 0.0:
        return 0.0
    query_seconds = max((query_end - query_start).total_seconds(), 1.0)
    return min(overlap_seconds / query_seconds, 1.0)


def _day_range(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start, start + timedelta(days=1))


def _week_range(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day.weekday())
    return (start, start + timedelta(days=7))


def _month_range(year: int, month: int, *, tz: tzinfo | None) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=tz)
    days = monthrange(year, month)[1]
    return (start, start + timedelta(days=days))
