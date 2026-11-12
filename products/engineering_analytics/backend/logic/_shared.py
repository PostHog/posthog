from datetime import datetime, timedelta

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.utils import relative_date_parse

DEFAULT_WINDOW = timedelta(days=30)
_DEFAULT_WINDOW = f"-{DEFAULT_WINDOW.days}d"

# workflow_health zero-fills one entry per workflow per day in the window, so the response
# grows with the range.
_MAX_WINDOW_DAYS = 366


def _parse_date(team: Team, value: str) -> datetime:
    return relative_date_parse(value, team.timezone_info)


def _parse_window(
    team: Team, date_from: str | None, date_to: str | None, *, default: str, max_days: int = _MAX_WINDOW_DAYS
) -> tuple[datetime, datetime | None]:
    """Resolve the window in the team's timezone. Raises ValueError when it is reversed or spans
    more than ``max_days``."""
    parsed_from = _parse_date(team, date_from or default)
    parsed_to = _parse_date(team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days < 0:
        raise ValueError("date_to must be on or after date_from")
    if span_days > max_days:
        raise ValueError(f"date window spans {span_days} days; the maximum is {max_days}")
    return parsed_from, parsed_to


@frozen
class ScanWindow:
    """``scan_from`` is the start of the equal-length window before the requested one."""

    scan_from: datetime
    resolved_to: datetime


@frozen
class WindowedCount:
    current: int | None
    prior: int | None


def _prior_window(date_from: datetime, date_to: datetime | None) -> ScanWindow:
    resolved_to = date_to or datetime.now(tz=date_from.tzinfo)
    return ScanWindow(scan_from=date_from - (resolved_to - date_from), resolved_to=resolved_to)


def _require_repo(repo: str | None) -> tuple[str, str]:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return owner, name


def _split_repo(repo: str | None) -> tuple[str | None, str | None]:
    if not repo:
        return None, None
    owner, _, name = repo.partition("/")
    # A half-specified repo would otherwise drop the filter and return rows from the wrong repo.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return owner, name
