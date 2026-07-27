"""Which teams the Duckgres batch sink is enabled for.

The sink must only claim batches for teams that (a) have a DuckgresServerTeam
membership and (b) have the rollout feature flag on. The membership is created
when the team completes the managed-warehouse enable flow. Claiming anything
else can switch an unregistered team from its legacy team-id schema to a newly
chosen suffix after the sink has already primed it.

The flag also provides mutual exclusion with the legacy
DuckLakeCopyDataImportsWorkflow (full-table copy after each import job): that
workflow skips teams where this flag is enabled, so a table never has two
uncoordinated duckgres writers.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import F

import structlog
import posthoganalytics

from posthog.ducklake.common import is_dev_mode
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

DUCKGRES_BATCH_SINK_FLAG = "duckgres-batch-sink"


def is_duckgres_sink_team_member(team_id: int) -> bool:
    """Whether a team has registered its membership in its org's Duckgres server.

    ``table_suffix`` is intentionally not part of this check. Legacy memberships
    with a NULL/empty suffix use the stable team-id schema naming fallback.
    """
    from posthog.ducklake.models import DuckgresServerTeam

    return DuckgresServerTeam.objects.filter(
        team_id=team_id,
        server__organization_id=F("team__organization_id"),
    ).exists()


@dataclass(frozen=True)
class SinkEnablement:
    """The sink's per-refresh view of who it serves and how hard it may push.

    ``team_org_budgets`` carries one (team_id, org_id, sink_max_concurrency)
    row per enabled team — the queue DB has no teams table, so the claim query
    receives this mapping as unnest'd arrays to enforce the per-org group
    budget fleet-wide.
    """

    team_ids: list[int]
    team_org_budgets: list[tuple[int, str, int]]


def duckgres_sink_enablement() -> SinkEnablement | None:
    """Enabled teams plus their org's sink concurrency budget, or None for
    "no filter, no budgets" (dev mode).

    Runs sync (Django ORM + flag evaluation); call via sync_to_async from the
    consumer. Raises on app-DB errors — the caller keeps its previous cached
    value so a transient app-DB blip doesn't blind the sink.

    The flag is evaluated only-locally (no per-team network round-trip) with the
    org/project group properties supplied inline, matching the data-warehouse-scene
    gate and the legacy copy-workflow gate. A team that can't be resolved locally
    evaluates falsy and is skipped (safe direction).
    """
    if is_dev_mode():
        return None

    from posthog.ducklake.models import DuckgresServerTeam

    enabled: list[int] = []
    team_org_budgets: list[tuple[int, str, int]] = []
    memberships = DuckgresServerTeam.objects.filter(server__organization_id=F("team__organization_id")).values_list(
        "team_id", "team__uuid", "team__organization_id", "server__sink_max_concurrency"
    )
    for team_id, team_uuid, org_id, sink_max_concurrency in memberships:
        try:
            if posthoganalytics.feature_enabled(
                DUCKGRES_BATCH_SINK_FLAG,
                str(team_uuid),
                groups={"organization": str(org_id), "project": str(team_id)},
                group_properties={
                    "organization": {"id": str(org_id)},
                    "project": {"id": str(team_id), "organization_id": str(org_id)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            ):
                enabled.append(team_id)
                team_org_budgets.append((team_id, str(org_id), sink_max_concurrency))
        except Exception as e:
            # Flag evaluation failing for one team must not blind the whole sink;
            # treat as disabled (safe direction: we skip, never wrongly claim).
            logger.exception("duckgres_sink_flag_evaluation_failed", team_id=team_id)
            capture_exception(e)
    return SinkEnablement(team_ids=enabled, team_org_budgets=team_org_budgets)


def duckgres_sink_team_ids() -> list[int] | None:
    """Back-compat view of duckgres_sink_enablement: just the enabled team ids."""
    enablement = duckgres_sink_enablement()
    return None if enablement is None else enablement.team_ids
