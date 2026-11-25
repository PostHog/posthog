from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.models import SandboxSenderTenantState
from products.workflows.backend.providers.ses import SESProvider

logger = get_logger(__name__)

MISSING_TENANT_STATUS = "UNKNOWN"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def sync_sandbox_sender_tenant_state() -> None:
    tenant_name = settings.SES_SANDBOX_TENANT_NAME
    if not tenant_name:
        return
    read_at = timezone.now()
    try:
        sending_status = SESProvider().get_tenant_sending_status(tenant_name)
    except Exception:
        logger.warning("sandbox_sender_tenant_state_read_failed", tenant_name=tenant_name, exc_info=True)
        return
    SandboxSenderTenantState.objects.get_or_create(tenant_name=tenant_name)
    SandboxSenderTenantState.objects.filter(
        Q(synced_at__isnull=True) | Q(synced_at__lt=read_at), tenant_name=tenant_name
    ).update(sending_status=sending_status or MISSING_TENANT_STATUS, synced_at=read_at)
