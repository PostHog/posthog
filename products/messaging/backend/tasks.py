from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio


@shared_task(ignore_result=True)
@skip_team_scope_audit  # MessageRecipientPreference is still on the default manager
def sync_preferences_to_customerio_task(team_id: int, identifier: str) -> None:
    """Push a recipient's current preference state to Customer.io off the request path.

    Reads the row fresh instead of taking a preferences snapshot as an argument, so two
    rapid writes to the same recipient can't sync out of order and leave Customer.io on
    the older state.
    """
    preference = MessageRecipientPreference.objects.filter(team_id=team_id, identifier=identifier).first()
    if preference is None:
        return
    sync_preferences_to_customerio(team_id, identifier, preference.preferences)
