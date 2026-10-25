from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC, the only timestamp format this project stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
