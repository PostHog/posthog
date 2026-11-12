from uuid import UUID

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.services.code_email_source import RETRIED_OUTCOMES, detect_code_email_source
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio


@shared_task(ignore_result=True, name="products.messaging.backend.tasks.sync_preferences_to_customerio_task")
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


# Stays under the Redis broker's one-hour visibility timeout, because a longer countdown makes the broker deliver
# the waiting retry a second time.
SOURCE_DETECTION_RETRY_SECONDS = 3000


@shared_task(ignore_result=True, name="products.messaging.backend.tasks.detect_code_email_source_task")
def detect_code_email_source_task(team_id: int, key_id: str, attempt: int = 1) -> None:
    """Link a new code email key to the file that sends it, and search once more 50 minutes later after a miss."""
    detection = detect_code_email_source(team_id, UUID(key_id), attempt=attempt)
    if detection is not None and attempt == 1 and detection.outcome in RETRIED_OUTCOMES:
        detect_code_email_source_task.apply_async(args=(team_id, key_id, 2), countdown=SOURCE_DETECTION_RETRY_SECONDS)
