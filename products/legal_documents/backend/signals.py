import dataclasses

import structlog

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import LegalDocument

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class LegalDocumentContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    document_type: str
    company_name: str


@mutable_receiver(model_activity_signal, sender=LegalDocument)
def handle_legal_document_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    instance: LegalDocument | None = after_update or before_update
    if instance is None:
        return

    context = LegalDocumentContext(
        organization_id=str(instance.organization_id),
        organization_name=instance.organization.name,
        document_type=instance.document_type,
        company_name=instance.company_name,
    )

    if activity == "created":
        detail_name = f"{instance.document_type} generated for {instance.company_name}"
    elif activity == "deleted":
        detail_name = f"{instance.document_type} deleted for {instance.company_name}"
    else:
        detail_name = f"{instance.document_type} updated for {instance.company_name}"

    log_activity(
        organization_id=instance.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
