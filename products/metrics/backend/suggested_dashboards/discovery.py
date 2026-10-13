"""Finds the teams whose metric names changed since their last analysis, or whose analysis predates a bank change."""

from __future__ import annotations

import datetime as dt

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

logger = structlog.get_logger(__name__)

NAMES_WINDOW = dt.timedelta(hours=24)
MAX_TEAMS_PER_SWEEP = 25
MAX_FINGERPRINT_TEAMS = 10_000
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


def teams_to_analyze(now: dt.datetime | None = None) -> list[int]:
    """The teams with the feature on whose names or bank revision changed, the longest-waiting first.

    The new fingerprints are saved here, so a team with no change is not picked again. A team with the
    feature off is recorded as seen, and its first analysis starts when someone opens its suggestions.
    """
    now = now or timezone.now()
    fingerprints = name_fingerprints(now)
    if not fingerprints:
        return []
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
    picked: list[int] = []
    for team_id in changed:
        if len(picked) >= MAX_TEAMS_PER_SWEEP:
            break
        team = teams.get(team_id)
        if team is None:
            continue
        enabled = suggestions_enabled(team)
        values: dict[str, object] = {"names_fingerprint": fingerprints[team_id]}
        if not enabled:
            values["bank_revision"] = revision
        MetricsDashboardDiscovery.objects.for_team(team_id).update_or_create(team_id=team_id, defaults=values)
        if enabled:
            picked.append(team_id)
    return picked


def needs_first_analysis(team_id: int) -> bool:
    state = MetricsDashboardDiscovery.objects.for_team(team_id).only("analyzed_at").first()
    return state is None or state.analyzed_at is None
