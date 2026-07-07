"""Which teams the Duckgres batch sink is enabled for.

The sink must only claim batches for teams that (a) belong to an org with a
provisioned DuckgresServer and (b) have the rollout feature flag on. Claiming
anything else burns retries, fails sink runs, and floods Sentry for orgs that
have no Duckgres to write to.

The flag also provides mutual exclusion with the legacy
DuckLakeCopyDataImportsWorkflow (full-table copy after each import job): that
workflow skips teams where this flag is enabled, so a table never has two
uncoordinated duckgres writers.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.ducklake.common import is_dev_mode
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)

DUCKGRES_BATCH_SINK_FLAG = "duckgres-batch-sink"


@close_db_connections
def duckgres_sink_team_ids() -> list[int] | None:
    """Team ids the sink may process, or None for "no filter" (dev mode).

    Runs sync (Django ORM + flag evaluation); call via sync_to_async from the
    consumer. Raises on app-DB errors — the caller keeps its previous cached
    set so a transient app-DB blip doesn't blind the sink.

    The consumer's poll loop is a long-lived thread-pool worker that never
    passes through Django's request cycle, so ``close_old_connections()`` never
    fires and a pooled connection reaped server-side would otherwise raise
    ``OperationalError: the connection is closed`` on the next read. The
    decorator evicts stale connections around the ORM reads so each refresh
    starts from a fresh connection.

    The flag is evaluated only-locally (no per-team network round-trip) with the
    org/project group properties supplied inline, matching the data-warehouse-scene
    gate and the legacy copy-workflow gate. A team that can't be resolved locally
    evaluates falsy and is skipped (safe direction).
    """
    if is_dev_mode():
        return None

    from posthog.ducklake.models import DuckgresServer
    from posthog.models import Team

    org_ids = list(
        DuckgresServer.objects.filter(organization_id__isnull=False).values_list("organization_id", flat=True)
    )
    if not org_ids:
        return []

    enabled: list[int] = []
    for team_id, team_uuid, org_id in Team.objects.filter(organization_id__in=org_ids).values_list(
        "id", "uuid", "organization_id"
    ):
        try:
            if posthoganalytics.feature_enabled(
                DUCKGRES_BATCH_SINK_FLAG,
                str(team_uuid),
                groups={"organization": str(org_id), "project": str(team_id)},
                group_properties={
                    "organization": {"id": str(org_id)},
                    "project": {"id": str(team_id)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            ):
                enabled.append(team_id)
        except Exception as e:
            # Flag evaluation failing for one team must not blind the whole sink;
            # treat as disabled (safe direction: we skip, never wrongly claim).
            logger.exception("duckgres_sink_flag_evaluation_failed", team_id=team_id)
            capture_exception(e)
    return enabled
