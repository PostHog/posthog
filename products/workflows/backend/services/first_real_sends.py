from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import batched
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import Q

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


class FirstRealSendCaptureError(Exception):
    pass


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
        first_sends[(team_id, hog_flow_id)] = first_send if first_send.tzinfo else first_send.replace(tzinfo=UTC)
    return first_sends


def capture_first_real_sends(now: datetime) -> int:
    first_sends = _first_billable_emails(now - FIRST_REAL_SEND_LOOKBACK)
    captured = 0
    failed_batches = 0
    first_error: Exception | None = None
    for batch in batched(first_sends.items(), CANDIDATE_BATCH_SIZE, strict=False):
        try:
            captured += _record_batch(dict(batch))
        except Exception as error:
            logger.exception(
                "workflows_first_real_send_batch_failed",
                candidate_hog_flow_ids=[str(hog_flow_id) for (_, hog_flow_id), _ in batch],
            )
            failed_batches += 1
            first_error = first_error or error
    logger.info("workflows_first_real_sends_captured", captured=captured, failed_batches=failed_batches)
    if first_error is not None:
        raise first_error
    return captured


def _record_batch(first_sends: dict[tuple[int, UUID], datetime]) -> int:
    hog_flow_ids_by_team: dict[int, list[UUID]] = defaultdict(list)
    for team_id, hog_flow_id in first_sends:
        hog_flow_ids_by_team[team_id].append(hog_flow_id)
    team_scoped_ids = Q()
    for team_id, team_hog_flow_ids in hog_flow_ids_by_team.items():
        team_scoped_ids |= Q(team_id=team_id, pk__in=team_hog_flow_ids)
    candidates = list(
        HogFlow.objects.filter(
            team_scoped_ids,
            created_at__gte=FIRST_REAL_SEND_CUTOFF,
            first_real_send_at__isnull=True,
        ).only("id", "team_id", "entry_attempt_id", "origin_product")
    )
    teams = Team.objects.only("id", "uuid", "organization_id").in_bulk({flow.team_id for flow in candidates})
    pending = sorted(
        (
            (flow, teams[flow.team_id], first_sends[(flow.team_id, flow.id)])
            for flow in candidates
            if flow.team_id in teams
        ),
        key=lambda item: item[0].id,
    )
    if not pending:
        return 0
    try:
        _capture(pending)
    except Exception as error:
        hog_flow_ids = [str(flow.id) for flow, _, _ in pending]
        logger.exception("workflows_first_real_send_capture_failed", hog_flow_ids=hog_flow_ids)
        raise FirstRealSendCaptureError(hog_flow_ids) from error
    with transaction.atomic():
        for flow, _, first_send in pending:
            HogFlow.objects.filter(pk=flow.pk, first_real_send_at__isnull=True).update(first_real_send_at=first_send)
    return len(pending)


def _capture(recorded: list[tuple[HogFlow, Team, datetime]]) -> None:
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
                    "$ignore_sent_at": True,
                },
                groups=groups(team=team),
            )
