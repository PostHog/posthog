"""Finds the teams whose metric names changed since their last analysis, or whose analysis predates a bank change."""

from __future__ import annotations

import datetime as dt

from django.core.cache import cache
from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team
from posthog.permissions import posthog_feature_flag_enabled

from products.metrics.backend.facade.contracts import METRICS_SUGGESTED_DASHBOARDS_FEATURE_FLAG
from products.metrics.backend.models import MetricsDashboardDiscovery
from products.metrics.backend.suggested_dashboards.analysis import bank_revision
from products.metrics.backend.suggested_dashboards.timeouts import SUGGEST_TIMEOUT

logger = structlog.get_logger(__name__)

NAMES_WINDOW = dt.timedelta(hours=24)
MAX_TEAMS_PER_SWEEP = 25
MAX_FINGERPRINT_TEAMS = 10_000
# A team is analyzed at most this often. A failed or slow analysis then cannot take a sweep slot every time.
RETRY_AFTER = dt.timedelta(minutes=30)
# A team whose users opened its suggestions this recently gets background analyses, whatever the flag
# says for the team. The flag can target people, which the sweep cannot evaluate.
OPENED_WINDOW = dt.timedelta(days=7)
_NEVER = dt.datetime.min.replace(tzinfo=dt.UTC)

# `metrics4_names` is the physical table behind the HogQL `metric_names` table: one row for each
# team, metric name, service and hour. The XOR of the name hashes changes whenever a name appears
# or goes away, so a sweep compares one number per team and reads no names.
_FINGERPRINT_QUERY = """
SELECT team_id, groupBitXor(cityHash64(metric_name)) AS fingerprint
FROM (
    SELECT DISTINCT team_id, metric_name
    FROM metrics4_names
    WHERE time_bucket >= %(since)s
)
GROUP BY team_id
LIMIT %(limit)s
"""


def _signed(value: int) -> int:
    # ClickHouse returns a UInt64, and Postgres stores a signed BigInteger.
    return value - (1 << 64) if value >= 1 << 63 else value


def name_fingerprints(now: dt.datetime) -> dict[int, int]:
    """A digest of the metric names of each team that sent metrics in the window."""
    with tags_context(product=Product.METRICS, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            _FINGERPRINT_QUERY,
            {
                "since": (now - NAMES_WINDOW)
                .astimezone(dt.UTC)
                .replace(minute=0, second=0, microsecond=0, tzinfo=None),
                "limit": MAX_FINGERPRINT_TEAMS,
            },
            workload=Workload.LOGS,
        )
    return {int(team_id): _signed(int(fingerprint)) for team_id, fingerprint in rows}


def suggestions_enabled(team: Team) -> bool:
    try:
        return posthog_feature_flag_enabled(
            METRICS_SUGGESTED_DASHBOARDS_FEATURE_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    except Exception:
        logger.warning("metrics_suggested_dashboards_flag_check_failed", team_id=team.id)
        return False


def teams_to_analyze(now: dt.datetime | None = None) -> dict[int, int]:
    """The teams to analyze, with their new name fingerprints, the longest-waiting first.

    A team is analyzed when its names or the bank changed, and either the flag is on for the team or one of
    its users opened its suggestions in the last week. The analysis records the fingerprint when it
    finishes, so a failed one is picked again, after RETRY_AFTER.
    Any other team is recorded as seen, and its first analysis starts when someone opens its suggestions.
    """
    now = now or timezone.now()
    fingerprints = name_fingerprints(now)
    if not fingerprints:
        return {}
    revision = bank_revision()
    states = {
        state.team_id: state
        for state in MetricsDashboardDiscovery.objects.unscoped().filter(team_id__in=list(fingerprints))
    }
    changed = sorted(
        (
            team_id
            for team_id, fingerprint in fingerprints.items()
            if (state := states.get(team_id)) is None
            or state.names_fingerprint != fingerprint
            or state.bank_revision != revision
        ),
        key=lambda team_id: (states[team_id].analyzed_at or _NEVER) if team_id in states else _NEVER,
    )
    teams = {team.id: team for team in Team.objects.filter(id__in=changed).only("id", "uuid", "organization_id")}
    opened = _recently_opened(changed)
    picked: dict[int, int] = {}
    for team_id in changed:
        if len(picked) >= MAX_TEAMS_PER_SWEEP:
            break
        team = teams.get(team_id)
        if team is None:
            continue
        state = states.get(team_id)
        if team_id in opened or suggestions_enabled(team):
            if state is not None and state.attempted_at is not None and state.attempted_at > now - RETRY_AFTER:
                continue
            picked[team_id] = fingerprints[team_id]
            continue
        MetricsDashboardDiscovery.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            defaults={"names_fingerprint": fingerprints[team_id], "bank_revision": revision, "noted_at": now},
        )
    return picked


def _analysis_on_open_key(team_id: int) -> str:
    return f"metrics_suggested_dashboards_first_analysis:{team_id}"


def _opened_key(team_id: int) -> str:
    return f"metrics_suggested_dashboards_opened:{team_id}"


def _recently_opened(team_ids: list[int]) -> set[int]:
    keys = {_opened_key(team_id): team_id for team_id in team_ids}
    try:
        found = cache.get_many(list(keys))
    except Exception:
        return set()
    return {keys[key] for key, value in found.items() if value}


def record_opened(team_id: int) -> None:
    """Note that a user of the team, for whom the flag is on, listed its suggestions."""
    try:
        cache.set(_opened_key(team_id), True, timeout=int(OPENED_WINDOW.total_seconds()))
    except Exception:
        logger.warning("metrics_suggested_dashboards_opened_not_recorded", team_id=team_id)


def needs_analysis_on_open(team_id: int) -> bool:
    """True when the team was never analyzed, or changed since its last analysis, and no analysis started recently.

    A sweep only notes the changes of a team that the flag check missed. Its next open analyzes them.
    The menu lists suggestions on every open, so without the cache each open would start a workflow.
    """
    state = MetricsDashboardDiscovery.objects.for_team(team_id).only("analyzed_at", "noted_at").first()
    if state is not None and state.analyzed_at is not None and state.noted_at is None:
        return False
    try:
        return cache.add(_analysis_on_open_key(team_id), True, timeout=int(SUGGEST_TIMEOUT.total_seconds()))
    except Exception:
        return True


def forget_analysis_on_open(team_id: int) -> None:
    """Let the next list start the first analysis again, after a start that failed."""
    try:
        cache.delete(_analysis_on_open_key(team_id))
    except Exception:
        logger.warning("metrics_suggested_dashboards_first_analysis_not_reset", team_id=team_id)
