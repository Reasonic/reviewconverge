"""Five-field cron expression parsing and next-run computation.

Supports the classic crontab layout::

    minute  hour  day-of-month  month  day-of-week

Each field accepts wildcards (``*``), inclusive ranges (``a-b``), stepped
ranges (``*/n`` and ``a-b/n``) and comma-separated lists mixing any of the
above. Month and day-of-week fields additionally accept three-letter names
(``jan``..``dec``, ``sun``..``sat``). Day-of-week accepts both ``0`` and ``7``
for Sunday.

The scheduling rule for the two "day" fields follows the widespread Vixie-cron
convention: when *both* day-of-month and day-of-week are restricted (i.e. not
``*``), a timestamp matches if *either* one matches. Otherwise both must match.

    expr = CronExpr.parse("*/15 9-17 * * mon-fri")
    expr.next_after(datetime(2026, 1, 1, 8, 3))
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_FIELD_BOUNDS = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dom": (1, 31),
    "month": (1, 12),
    "dow": (0, 6),
}


class CronParseError(ValueError):
    """Raised when a cron expression is syntactically invalid."""


def _normalize_token(token: str, field: str) -> str:
    lowered = token.lower()
    if field == "month" and lowered in _MONTH_NAMES:
        return str(_MONTH_NAMES[lowered])
    if field == "dow" and lowered in _DOW_NAMES:
        return str(_DOW_NAMES[lowered])
    return lowered


def _parse_int(text: str, field: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise CronParseError(f"invalid number {text!r} in {field} field") from exc


def _expand_atom(atom: str, field: str) -> List[int]:
    """Expand one comma-free atom into the set of integers it covers."""
    low, high = _FIELD_BOUNDS[field]

    step = 1
    if "/" in atom:
        base, _, step_text = atom.partition("/")
        step = _parse_int(step_text, field)
        if step <= 0:
            raise CronParseError(f"step must be positive in {field} field")
    else:
        base = atom

    if base == "*":
        start, stop = low, high
    elif "-" in base and not base.startswith("-"):
        start_text, _, stop_text = base.partition("-")
        start = _parse_int(_normalize_token(start_text, field), field)
        stop = _parse_int(_normalize_token(stop_text, field), field)
    else:
        value = _parse_int(_normalize_token(base, field), field)
        if "/" in atom:
            start, stop = value, high
        else:
            start = stop = value

    values = _materialize_range(start, stop, step, field, low, high)
    return values


def _materialize_range(
    start: int, stop: int, step: int, field: str, low: int, high: int
) -> List[int]:
    if field == "dow":
        start = 0 if start == 7 else start
        stop = 0 if stop == 7 else stop
    if start < low or start > high or stop < low or stop > high:
        raise CronParseError(
            f"value out of range for {field} field (allowed {low}-{high})"
        )
    if start <= stop:
        span = range(start, stop + 1, step)
        return list(span)
    wrapped = list(range(start, high + 1)) + list(range(low, stop))
    return wrapped[::step]


def _parse_field(spec: str, field: str) -> Tuple[int, ...]:
    if spec.strip() == "":
        raise CronParseError(f"empty {field} field")
    collected: set = set()
    for atom in spec.split(","):
        atom = atom.strip()
        if not atom:
            raise CronParseError(f"empty list element in {field} field")
        for value in _expand_atom(atom, field):
            collected.add(value)
    if field == "dow":
        collected = {0 if v == 7 else v for v in collected}
    return tuple(sorted(collected))


@dataclass(frozen=True)
class CronExpr:
    """A parsed cron expression with precomputed allowed value sets."""

    minutes: Tuple[int, ...]
    hours: Tuple[int, ...]
    days_of_month: Tuple[int, ...]
    months: Tuple[int, ...]
    days_of_week: Tuple[int, ...]
    dom_restricted: bool
    dow_restricted: bool
    source: str

    @classmethod
    def parse(cls, s: str) -> "CronExpr":
        parts = s.split()
        if len(parts) != 5:
            raise CronParseError(
                f"expected 5 fields, got {len(parts)}: {s!r}"
            )
        minute_spec, hour_spec, dom_spec, month_spec, dow_spec = parts
        return cls(
            minutes=_parse_field(minute_spec, "minute"),
            hours=_parse_field(hour_spec, "hour"),
            days_of_month=_parse_field(dom_spec, "dom"),
            months=_parse_field(month_spec, "month"),
            days_of_week=_parse_field(dow_spec, "dow"),
            dom_restricted=_is_restricted(dom_spec),
            dow_restricted=_is_restricted(dow_spec),
            source=s.strip(),
        )

    def _day_matches(self, moment: datetime) -> bool:
        dom_ok = moment.day in self.days_of_month
        dow_ok = _weekday_cron(moment) in self.days_of_week
        if self.dom_restricted or self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def matches(self, moment: datetime) -> bool:
        """Return True if ``moment`` (to minute resolution) satisfies the rule."""
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and moment.month in self.months
            and self._day_matches(moment)
        )

    def next_after(self, dt: datetime) -> datetime:
        """Return the earliest minute strictly greater than ``dt`` that matches."""
        candidate = _truncate_to_minute(dt) + timedelta(minutes=1)
        limit = candidate + timedelta(days=366 * 8)

        while candidate <= limit:
            if candidate.month not in self.months:
                candidate = _advance_month(candidate)
                continue
            if not self._day_matches(candidate):
                candidate = _next_midnight(candidate)
                continue
            if candidate.hour not in self.hours:
                candidate = _next_hour(candidate)
                continue
            if candidate.minute not in self.minutes:
                candidate = _next_matching_minute(candidate, self.minutes)
                continue
            return candidate

        raise ValueError("no matching time found within horizon")

    def upcoming(self, dt: datetime, count: int) -> List[datetime]:
        """Return the next ``count`` run times after ``dt``."""
        out: List[datetime] = []
        cursor = dt
        for _ in range(count):
            cursor = self.next_after(cursor)
            out.append(cursor)
        return out


def _is_restricted(spec: str) -> bool:
    """A field is 'restricted' if it is not a bare or fully-covering wildcard."""
    cleaned = spec.strip()
    if cleaned == "*":
        return False
    if all(part.strip() == "*" for part in cleaned.split(",")):
        return False
    if cleaned.startswith("*/"):
        return False
    return True


def _weekday_cron(moment: datetime) -> int:
    """Map ``datetime.weekday()`` (Mon=0) to cron numbering (Sun=0)."""
    return (moment.weekday() - 1) % 7


def _truncate_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _advance_month(dt: datetime) -> datetime:
    if dt.month == 11:
        return dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0)
    return dt.replace(month=dt.month + 1, day=1, hour=0, minute=0)


def _next_midnight(dt: datetime) -> datetime:
    return _truncate_to_minute(dt).replace(hour=0, minute=0) + timedelta(days=1)


def _next_hour(dt: datetime) -> datetime:
    base = dt.replace(minute=0)
    return base + timedelta(hours=1)


def _next_matching_minute(dt: datetime, minutes: Sequence[int]) -> datetime:
    for minute in minutes:
        if minute > dt.minute:
            return dt.replace(minute=minute)
    return dt.replace(minute=0) + timedelta(hours=1)


def describe(expr: CronExpr) -> Dict[str, Sequence[int]]:
    """Return a plain dict view of the expanded field sets (handy for tests)."""
    return {
        "minutes": expr.minutes,
        "hours": expr.hours,
        "days_of_month": expr.days_of_month,
        "months": expr.months,
        "days_of_week": expr.days_of_week,
    }


def _demo() -> None:
    now = datetime(2026, 1, 1, 8, 3, 30)
    for spec in [
        "*/15 9-17 * * mon-fri",
        "0 0 1 * *",
        "30 4 * * 0",
        "0 12 1-7 jan,jul *",
        "5 0-2/1 * * *",
    ]:
        expr = CronExpr.parse(spec)
        runs = expr.upcoming(now, 3)
        printable = ", ".join(r.strftime("%Y-%m-%d %H:%M %a") for r in runs)
        print(f"{spec:24s} -> {printable}")

    weekend = CronExpr.parse("0 9 13 * fri")
    hits = weekend.upcoming(datetime(2026, 1, 1, 0, 0), 4)
    print("Friday-the-13th-or-13th 09:00:", [h.strftime("%Y-%m-%d %a") for h in hits])


if __name__ == "__main__":
    _demo()
