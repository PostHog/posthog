from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import batched
from uuid import UUID, uuid5

from django.db import transaction

import structlog

from posthog.schema import ProductKey

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.clickhouse.workload import Workload
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.utils import get_instance_region

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)

WORKFLOW_FIRST_REAL_SEND_EVENT = "workflow first real send"
FIRST_REAL_SEND_CUTOFF = datetime(2026, 12, 1, tzinfo=UTC)
FIRST_REAL_SEND_LOOKBACK = timedelta(days=2)
CANDIDATE_BATCH_SIZE = 1000

FIRST_BILLABLE_EMAIL_SQL = """
SELECT team_id, app_source_id, min(timestamp)
FROM app_metrics2
WHERE app_source = 'hog_flow'
  AND metric_name = 'billable_invocation'
  AND metric_kind = 'email'
  AND timestamp >= %(since)s
GROUP BY team_id, app_source_id
"""


def _first_billable_emails(since: datetime) -> dict[tuple[int, UUID], datetime]:
    with tags_context(product=ProductKey.WORKFLOWS, feature=Feature.ENRICHMENT):
        rows = sync_execute(FIRST_BILLABLE_EMAIL_SQL, {"since": since}, workload=Workload.OFFLINE)
    first_sends: dict[tuple[int, UUID], datetime] = {}
    for team_id, app_source_id, first_send in rows:
        try:
            hog_flow_id = UUID(app_source_id)
        except ValueError:
            continue
        first_sends[(team_id, hog_flow_id)] = first_send
    return first_sends


def capture_first_real_sends(now: datetime) -> int:
    first_sends = _first_billable_emails(now - FIRST_REAL_SEND_LOOKBACK)
    captured = 0
    for batch in batched(first_sends.items(), CANDIDATE_BATCH_SIZE, strict=False):
        captured += _record_batch(dict(batch))
    logger.info("workflows_first_real_sends_captured", captured=captured)
    return captured


def _record_batch(first_sends: dict[tuple[int, UUID], datetime]) -> int:
    hog_flow_ids_by_team: dict[int, list[UUID]] = defaultdict(list)
    for team_id, hog_flow_id in first_sends:
        hog_flow_ids_by_team[team_id].append(hog_flow_id)
    candidates = [
        flow
        for team_id, hog_flow_ids in hog_flow_ids_by_team.items()
        for flow in HogFlow.objects.filter(
            team_id=team_id,
            pk__in=hog_flow_ids,
            created_at__gte=FIRST_REAL_SEND_CUTOFF,
            first_real_send_at__isnull=True,
        ).only("id", "team_id", "entry_attempt_id", "origin_product")
    ]
    teams = Team.objects.only("id", "uuid", "organization_id").in_bulk({flow.team_id for flow in candidates})
    recorded = []
    with transaction.atomic():
        for flow in candidates:
            team = teams.get(flow.team_id)
            if team is None:
                continue
            first_send = first_sends[(flow.team_id, flow.id)]
            if HogFlow.objects.filter(pk=flow.pk, first_real_send_at__isnull=True).update(
                first_real_send_at=first_send
            ):
                recorded.append((flow, team, first_send))
    if not recorded:
        return 0
    with ph_scoped_capture(event_region=get_instance_region(), raise_on_error=True) as capture:
        for flow, team, first_send in recorded:
            capture(
                distinct_id=str(team.uuid),
                event=WORKFLOW_FIRST_REAL_SEND_EVENT,
                timestamp=first_send,
                uuid=str(uuid5(flow.id, WORKFLOW_FIRST_REAL_SEND_EVENT)),
                properties={
                    "hog_flow_id": str(flow.id),
                    "entry_attempt_id": str(flow.entry_attempt_id) if flow.entry_attempt_id else None,
                    "origin_product": flow.origin_product,
                    "first_real_send_at": first_send.isoformat(),
                },
                groups=groups(team=team),
            )
    return len(recorded)
