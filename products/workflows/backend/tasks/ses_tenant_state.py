from celery import shared_task
from structlog import get_logger

from posthog.models.integration import Integration
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers.ses import SESProvider
from products.workflows.backend.services.ses_tenant_state import sync_ses_tenant_state

logger = get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    # The sync hits the SES API; transient throttling/outages should retry with backoff instead
    # of dropping the event (the daily sweep would catch it, but a day late).
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=5,
    retry_jitter=True,
)
def sync_ses_tenant_state_task(team_id: int) -> None:
    """Webhook-triggered: an EventBridge event said this team's tenant changed — fetch and apply."""
    sync_ses_tenant_state(team_id)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def reconcile_ses_tenant_states() -> None:
    """
    Periodic backstop: EventBridge delivery is best-effort, so sweep every team that has an SES
    tenant (i.e. a verified email integration) and apply the authoritative state. The transition
    logic dedupes against stored state, so overlap with webhook-triggered syncs is harmless.
    """
    team_ids = (
        Integration.objects.filter(kind="email", config__provider="ses")
        .values_list("team_id", flat=True)
        .distinct()
        .order_by("team_id")
    )
    # One provider for the whole sweep: a fresh SESProvider per team would rebuild its boto3
    # clients (and re-resolve credentials) thousands of times.
    provider = SESProvider()
    synced = 0
    failed = 0
    for team_id in team_ids.iterator(chunk_size=500):
        try:
            sync_ses_tenant_state(team_id, provider=provider, verify_team=False)
            synced += 1
        except Exception:
            failed += 1
            logger.exception("SES tenant reconciliation failed for team", team_id=team_id)
    logger.info("SES tenant reconciliation finished", synced=synced, failed=failed)
