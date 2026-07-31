"""Which teams the Duckgres batch sink is enabled for.

The sink must only claim batches for teams that (a) have a team row in their org's
duckgres control plane and (b) have the rollout feature flag on. The row is created
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

import structlog
import posthoganalytics

from posthog.ducklake import cp_teams
from posthog.ducklake.common import _get_org_id_for_team, is_dev_mode
from posthog.ducklake.team_state import CPUnavailableError
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

DUCKGRES_BATCH_SINK_FLAG = "duckgres-batch-sink"


def is_duckgres_sink_team_member(team_id: int) -> bool:
    """Whether a team has registered its membership in its org's Duckgres warehouse.

    Membership is the team's row in the duckgres control plane; whether the row derives
    or pins its schema names is intentionally not part of this check. Raises when the
    control plane can't answer — the caller decides how to degrade.
    """
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id, use_cache=False)
    if teams is None:
        raise RuntimeError(f"duckgres control plane unreachable resolving sink membership for team {team_id}")
    return any(team.team_id == team_id for team in teams)


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

    Runs sync (control-plane read + Django ORM + flag evaluation); call via
    sync_to_async from the consumer. Raises on app-DB errors or an unreachable
    control plane — the caller keeps its previous cached value so a transient
    blip doesn't blind the sink.

    The flag is evaluated only-locally (no per-team network round-trip) with the
    org/project group properties supplied inline, matching the data-warehouse-scene
    gate and the legacy copy-workflow gate. A team that can't be resolved locally
    evaluates falsy and is skipped (safe direction).
    """
    if is_dev_mode():
        return None

    from posthog.ducklake.models import DuckgresServer
    from posthog.models.team.team import Team

    rows = cp_teams.list_member_teams(use_cache=False)
    if rows is None:
        raise CPUnavailableError("duckgres control plane unreachable; keeping the previous sink enablement")

    team_info = {
        team_id: (str(team_uuid), str(org_id))
        for team_id, team_uuid, org_id in Team.objects.filter(id__in=[row.team_id for row in rows]).values_list(
            "id", "uuid", "organization_id"
        )
    }
    # Filtered by the app DB's own org ids, never by the control plane's row.organization_id:
    # that value is an external, unvalidated string (the CP has test/dev rows keyed by
    # human-readable slugs, not UUIDs), and passing it straight into a UUID FK lookup
    # raises ValidationError before the org_id match-up below ever runs.
    budgets = {
        str(org_id): sink_max_concurrency
        for org_id, sink_max_concurrency in DuckgresServer.objects.filter(
            organization_id__in={org_id for _, org_id in team_info.values()}
        ).values_list("organization_id", "sink_max_concurrency")
    }

    enabled: list[int] = []
    team_org_budgets: list[tuple[int, str, int]] = []
    for row in rows:
        info = team_info.get(row.team_id)
        if info is None:
            continue
        team_uuid, org_id = info
        if org_id.lower() != row.organization_id.lower():
            # A control-plane row whose org doesn't match the team's own org is not a
            # membership of that team's warehouse — mirror the old server-org join.
            continue
        sink_max_concurrency = budgets.get(org_id)
        if sink_max_concurrency is None:
            # No connection row means the sink can't reach the org's server anyway.
            continue
        try:
            if posthoganalytics.feature_enabled(
                DUCKGRES_BATCH_SINK_FLAG,
                team_uuid,
                groups={"organization": org_id, "project": str(row.team_id)},
                group_properties={
                    "organization": {"id": org_id},
                    "project": {"id": str(row.team_id), "organization_id": org_id},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            ):
                enabled.append(row.team_id)
                team_org_budgets.append((row.team_id, org_id, sink_max_concurrency))
        except Exception as e:
            # Flag evaluation failing for one team must not blind the whole sink;
            # treat as disabled (safe direction: we skip, never wrongly claim).
            logger.exception("duckgres_sink_flag_evaluation_failed", team_id=row.team_id)
            capture_exception(e)
    return SinkEnablement(team_ids=enabled, team_org_budgets=team_org_budgets)
