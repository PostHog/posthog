"""Caller-input resolution shared by the domain orchestration modules."""

from datetime import datetime

from posthog.models.team import Team
from posthog.utils import relative_date_parse

# Default recency window when a caller omits date_from. Relative strings (-30d) and
# ISO8601 are both accepted and resolved against the team's timezone.
_DEFAULT_WINDOW = "-30d"

# workflow_health zero-fills one daily entry per workflow per day in the window, so an
# unbounded range would materialize an enormous response. A year is plenty for trends.
_MAX_WINDOW_DAYS = 366


def _parse_date(team: Team, value: str) -> datetime:
    return relative_date_parse(value, team.timezone_info)


def _parse_window(
    team: Team, date_from: str | None, date_to: str | None, *, default: str, max_days: int = _MAX_WINDOW_DAYS
) -> tuple[datetime, datetime | None]:
    """Resolve a caller's date window against the team timezone, capping the span at max_days."""
    parsed_from = _parse_date(team, date_from or default)
    parsed_to = _parse_date(team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days < 0:
        raise ValueError("date_to must be on or after date_from")
    if span_days > max_days:
        raise ValueError(f"date window spans {span_days} days; the maximum is {max_days}")
    return parsed_from, parsed_to


def _require_repo(repo: str | None) -> tuple[str, str]:
    """`_split_repo` for builders whose repo argument is mandatory."""
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return owner, name


def _split_repo(repo: str | None) -> tuple[str | None, str | None]:
    if not repo:
        return None, None
    owner, _, name = repo.partition("/")
    # A half-specified repo (bare org, trailing/leading slash) would otherwise drop
    # the filter silently and return a PR from the wrong repo — fail loudly instead.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return owner, name
