from calendar import monthrange
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def add_months(dt: datetime, months: int = 1) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def family_now(tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def day_bounds(tz_name: str, day: datetime | None = None) -> tuple[datetime, datetime]:
    now = day or family_now(tz_name)
    local = now.astimezone(ZoneInfo(tz_name) if _valid_tz(tz_name) else ZoneInfo("UTC"))
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
