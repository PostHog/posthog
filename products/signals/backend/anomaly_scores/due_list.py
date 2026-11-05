"""The stored due list of the anomaly scoring tick, and the slow refresh that keeps it.

With `due_list` on, the tick plans from the due rows and sends no scored state query to ClickHouse. The list
can be stale. A pick of an insight that is already done waits for the attempt cooldown, and the backfill
scores the buckets of an insight that the list shows as due late.

The refresh adds the active insights of each enrolled team, removes the insights that left, and sets the
usage. Each pick then moves its own row, so the list stays close to right between two refreshes.
"""

import time
import datetime
from collections.abc import Collection

from django.core.cache import cache

import structlog

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team

from products.signals.backend.anomaly_scores.config import AnomalyScoringConfig, ScoringLimits
from products.signals.backend.anomaly_scores.queue import (
    ATTEMPT_COOLDOWN,
    ActiveInsight,
    TeamCensus,
    active_insights,
    due_at,
    eligible_teams,
    parse_watermarks,
    reason_counts,
    scored_buckets,
    scored_state_since,
    team_census,
)
from products.signals.backend.anomaly_scores.selection import insight_usage
from products.signals.backend.models import AnomalyScoringDueInsight, AnomalyScoringState

logger = structlog.get_logger(__name__)

# The last refresh of a team. It lives past the longest refresh window, so a team waits for its turn.
_TEAM_REFRESHED_TTL = datetime.timedelta(days=3)


@frozen
class TeamRefresh:
    census: TeamCensus
    added: int
    removed: int


@frozen
class DueListRefresh:
    enabled: bool = False
    teams_refreshed: int = 0
    teams_failed: int = 0
    # Teams past their refresh window that wait for a later run.
    teams_waiting: int = 0
    rows_added: int = 0
    rows_removed: int = 0
    # Active insights of the refreshed teams, and how many of them have each activity reason.
    active: int = 0
    active_reasons: dict[str, int] | None = None
    census: list[TeamCensus] | None = None


def _team_refreshed_key(team_id: int) -> str:
    return f"signals:anomaly_scores:due_list_refreshed:{team_id}"


def dump_watermarks(watermarks: dict[str, datetime.datetime]) -> dict[str, str]:
    return {key: bucket.astimezone(datetime.UTC).isoformat() for key, bucket in watermarks.items()}


def seed_watermarks(
    config: AnomalyScoringConfig, team: Team, insights: Collection[ActiveInsight], now: datetime.datetime
) -> dict[int, dict[str, datetime.datetime]]:
    """The scored state of insights new to the list.

    A stored model gives each of its series the newest scored bucket of the model, so the switch causes no
    retrain. Only insights with no stored model read their state from ClickHouse, once, when they join the list.
    """
    if not insights:
        return {}
    seeded: dict[int, dict[str, datetime.datetime]] = {}
    rows = (
        AnomalyScoringState.objects.for_team(team.id)
        .filter(insight_id__in=[insight.insight_id for insight in insights], scored_through__isnull=False)
        .values_list("insight_id", "scored_through", "series_keys")
    )
    for insight_id, scored_through, series_keys in rows:
        if scored_through is None or not isinstance(series_keys, list):
            continue
        watermarks = seeded.setdefault(insight_id, {})
        for series_key in series_keys:
            watermarks[str(series_key)] = max(watermarks.get(str(series_key), scored_through), scored_through)
    windows: dict[datetime.datetime, set[int]] = {}
    for insight in insights:
        if not seeded.get(insight.insight_id):
            windows.setdefault(scored_state_since(config, insight.interval, now), set()).add(insight.insight_id)
    if windows:
        seeded.update(scored_buckets(team, windows, now))
    return seeded


def refresh_team(config: AnomalyScoringConfig, team: Team, now: datetime.datetime) -> TeamRefresh:
    insights = active_insights([team.id], config.intervals, now, config.active_window_days)
    by_id = {insight.insight_id: insight for insight in insights}
    scope = AnomalyScoringDueInsight.all_teams.filter(team_id=team.id)
    removed, _ = scope.exclude(insight_id__in=list(by_id)).delete()
    existing = {row.insight_id: row for row in scope.filter(insight_id__in=list(by_id))}
    seeded = seed_watermarks(config, team, [insight for insight in insights if insight.insight_id not in existing], now)
    usage = insight_usage(team_id=team.id, insight_ids=list(by_id), now=now)

    created: list[AnomalyScoringDueInsight] = []
    updated: list[AnomalyScoringDueInsight] = []
    for insight in insights:
        row = existing.get(insight.insight_id)
        watermarks = parse_watermarks(row.series_scored_through) if row else seeded.get(insight.insight_id, {})
        next_due_at = (
            due_at(insight.insight_id, insight.interval, max(watermarks.values(), default=None), team.timezone_info)
            or now
        )
        if row is not None and row.interval == insight.interval.value:
            # A failed pick moved the row past its cooldown.
            next_due_at = max(next_due_at, row.next_due_at)
        fields = {
            "interval": insight.interval.value,
            "next_due_at": next_due_at,
            "refreshed_at": now,
            "viewers": usage[insight.insight_id].viewers,
            "has_enabled_alert": usage[insight.insight_id].has_enabled_alert,
        }
        if row is None:
            created.append(
                AnomalyScoringDueInsight(
                    team_id=team.id,
                    insight_id=insight.insight_id,
                    series_scored_through=dump_watermarks(watermarks),
                    **fields,
                )
            )
            continue
        for name, value in fields.items():
            setattr(row, name, value)
        row.updated_at = now
        updated.append(row)
    # A pick writes the watermarks of its own row, so the refresh never writes them for an existing row.
    AnomalyScoringDueInsight.all_teams.bulk_create(created, ignore_conflicts=True)
    AnomalyScoringDueInsight.all_teams.bulk_update(
        updated, ["interval", "next_due_at", "refreshed_at", "viewers", "has_enabled_alert", "updated_at"]
    )
    [census] = team_census([team.id], insights)
    return TeamRefresh(census=census, added=len(created), removed=removed)


def refresh_due_list(config: AnomalyScoringConfig, now: datetime.datetime, deadline: float) -> DueListRefresh:
    """Refresh the teams past their refresh window, the longest waiting first, until ``deadline``.

    ``deadline`` is a ``time.monotonic`` value. At least one team refreshes per run. A failed team also goes to
    the back, so a team that always fails does not block the others.
    """
    if not config.enabled or not config.due_list:
        return DueListRefresh()
    teams = {team.id: team for team in eligible_teams(config)}
    stamps = cache.get_many([_team_refreshed_key(team_id) for team_id in teams])
    window_start = (now - datetime.timedelta(hours=config.due_list_refresh_hours)).timestamp()
    waiting = sorted(
        (team_id for team_id in teams if stamps.get(_team_refreshed_key(team_id), 0.0) <= window_start),
        key=lambda team_id: (stamps.get(_team_refreshed_key(team_id), 0.0), team_id),
    )
    census: list[TeamCensus] = []
    attempted = failed = added = removed = 0
    for team_id in waiting:
        if attempted and time.monotonic() >= deadline:
            break
        attempted += 1
        try:
            refresh = refresh_team(config, teams[team_id], now)
        except Exception as error:
            failed += 1
            logger.warning(
                "anomaly_scoring_due_list_refresh_failed",
                team_id=team_id,
                error_class=type(error).__name__,
                exc_info=True,
            )
        else:
            census.append(refresh.census)
            added += refresh.added
            removed += refresh.removed
        cache.set(_team_refreshed_key(team_id), now.timestamp(), timeout=int(_TEAM_REFRESHED_TTL.total_seconds()))
    return DueListRefresh(
        enabled=True,
        teams_refreshed=attempted - failed,
        teams_failed=failed,
        teams_waiting=len(waiting) - attempted,
        rows_added=added,
        rows_removed=removed,
        active=sum(team.active for team in census),
        active_reasons={reason: sum(team.active_reasons[reason] for team in census) for reason in reason_counts([])},
        census=census,
    )


def record_scored(
    team: Team,
    insight_id: int,
    watermarks: dict[str, datetime.datetime],
    now: datetime.datetime,
    limits: ScoringLimits,
) -> None:
    """Merge the newest scored bucket of each series into the insight's row, and set when it is due next."""
    row = AnomalyScoringDueInsight.all_teams.filter(team_id=team.id, insight_id=insight_id).first()
    if row is None:
        return
    interval = IntervalType(row.interval)
    merged = parse_watermarks(row.series_scored_through)
    for series_key, bucket in watermarks.items():
        merged[series_key] = max(merged.get(series_key, bucket), bucket)
    # A series older than the backfill cap scores as a new series, so its entry has no effect.
    since = now - interval_spec(interval).period * (limits.max_backfill_buckets + 1)
    kept = {series_key: bucket for series_key, bucket in merged.items() if bucket >= since}
    due = due_at(insight_id, interval, max(kept.values(), default=None), team.timezone_info)
    # A visit with no new bucket must not make the row due again before the cooldown ends.
    row.next_due_at = max(due or now, now + ATTEMPT_COOLDOWN)
    row.series_scored_through = dump_watermarks(kept)
    row.save(update_fields=["next_due_at", "series_scored_through", "updated_at"])


def record_failed(team_id: int, insight_id: int, now: datetime.datetime, cooldown: datetime.timedelta) -> None:
    """Move the insight's row past the cooldown of a failed pick."""
    AnomalyScoringDueInsight.all_teams.filter(team_id=team_id, insight_id=insight_id).update(
        next_due_at=now + cooldown, updated_at=now
    )
