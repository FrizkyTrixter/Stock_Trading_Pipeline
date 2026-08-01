"""UTC-only clock helpers."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(UTC)
