import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def family_zone(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name) if _valid_tz(tz_name) else ZoneInfo("UTC")


def parse_year_month(value: str) -> tuple[int, int]:
    match = YEAR_MONTH_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("month must be YYYY-MM")
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise ValueError("month must be YYYY-MM")
    return year, month


def add_calendar_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def month_key(dt: datetime, tz_name: str) -> str:
    local = ensure_aware(dt).astimezone(family_zone(tz_name))
    return f"{local.year:04d}-{local.month:02d}"


def month_bounds(
    tz_name: str, year: int | None = None, month: int | None = None
) -> tuple[datetime, datetime]:
    tz = family_zone(tz_name)
    now = family_now(tz_name)
    y = year if year is not None else now.year
    m = month if month is not None else now.month
    start = datetime(y, m, 1, tzinfo=tz)
    next_y, next_m = add_calendar_months(y, m, 1)
    end = datetime(next_y, next_m, 1, tzinfo=tz)
    return start, end


def add_months(dt: datetime, months: int = 1) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def family_now(tz_name: str) -> datetime:
    return datetime.now(family_zone(tz_name))


def day_bounds(tz_name: str, day: datetime | None = None) -> tuple[datetime, datetime]:
    now = day or family_now(tz_name)
    local = now.astimezone(family_zone(tz_name))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def next_occurrence(from_dt: datetime, rule: str) -> datetime | None:
    """Compute next occurrence for simple recurrence rules used in MVP."""
    dt = ensure_aware(from_dt)
    rule_l = (rule or "").strip().lower()
    rule_u = (rule or "").upper()
    if not rule_l or rule_l in ("none", "never"):
        return None
    if rule_l == "daily" or "FREQ=DAILY" in rule_u:
        return dt + timedelta(days=1)
    if rule_l == "weekly" or "FREQ=WEEKLY" in rule_u:
        return dt + timedelta(weeks=1)
    if rule_l == "monthly" or "FREQ=MONTHLY" in rule_u:
        return add_months(dt, 1)
    # Custom weekdays: e.g. "weekdays:mon,wed,fri"
    if rule_l.startswith("weekdays:"):
        names = rule_l.split(":", 1)[1].split(",")
        mapping = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        days = sorted({mapping[n.strip()[:3]] for n in names if n.strip()[:3] in mapping})
        if not days:
            return None
        for i in range(1, 8):
            candidate = dt + timedelta(days=i)
            if candidate.weekday() in days:
                return candidate
        return None
    return None


def expand_occurrences(
    starts_at: datetime,
    recurrence_rule: str | None,
    window_start: datetime,
    window_end: datetime,
    max_instances: int = 200,
) -> list[datetime]:
    start = ensure_aware(starts_at)
    ws = ensure_aware(window_start)
    we = ensure_aware(window_end)
    if not recurrence_rule:
        return [start] if ws <= start < we else []

    instances: list[datetime] = []
    cursor = start
    # Walk forward from original start until past window
    guard = 0
    while cursor < we and guard < max_instances * 3:
        if cursor >= ws:
            instances.append(cursor)
            if len(instances) >= max_instances:
                break
        nxt = next_occurrence(cursor, recurrence_rule)
        if nxt is None or nxt <= cursor:
            break
        cursor = nxt
        guard += 1
    return instances
