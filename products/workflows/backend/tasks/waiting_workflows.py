from collections.abc import Sequence

from django.db import DatabaseError

from celery import shared_task
from prometheus_client import Counter
from redis.exceptions import RedisError
from structlog import get_logger

from posthog.event_usage import groups
from posthog.models import Team, User
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.facade.contracts import StatusChange

logger = get_logger(__name__)

ENABLE_WAITING_MAX_RETRIES = 5

enable_waiting_failed_total = Counter(
    "workflows_enable_waiting_failed_total",
    "Verified email senders whose waiting workflows could not go live after the last retry. "
    "Those workflows keep waiting until a person enables them again.",
)


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=ENABLE_WAITING_MAX_RETRIES,
    autoretry_for=(DatabaseError, RedisError),
    retry_backoff=True,
)
@skip_team_scope_audit
def enable_waiting_workflows_task(self, team_id: int, sender_ids: list[int]) -> None:
    # Deferred because the writes module imports this tasks package.
    from products.workflows.backend.services.hog_flow_writes import enable_waiting  # noqa: PLC0415

    try:
        changes = enable_waiting(team_id=team_id, sender_ids=frozenset(sender_ids))
    except (DatabaseError, RedisError):
        if self.request.retries < ENABLE_WAITING_MAX_RETRIES:
            raise
        logger.exception("workflows.enable_waiting.failed", team_id=team_id, sender_ids=sender_ids)
        enable_waiting_failed_total.inc()
        return
    _send_events(team_id, changes)


def _send_events(team_id: int, changes: Sequence[StatusChange]) -> None:
    events = [event for change in changes for event in change.events]
    if not events:
        return
    team = Team.objects.get(pk=team_id)
    users = User.objects.in_bulk({event.user_id for event in events if event.user_id is not None})
    try:
        with ph_scoped_capture() as capture:
            for event in events:
                user = users.get(event.user_id) if event.user_id is not None else None
                if user is None:
                    continue
                capture(
                    distinct_id=user.distinct_id,
                    event=event.name,
                    properties={
                        "workflow_id": str(event.workflow_id),
                        "team_id": str(team.id),
                        "organization_id": str(team.organization_id),
                        **event.properties,
                    },
                    groups=groups(team=team),
                )
    except Exception as e:
        logger.warning("Failed to capture workflow usage event", team_id=team_id, error=str(e))
