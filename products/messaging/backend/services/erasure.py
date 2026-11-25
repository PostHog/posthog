import hashlib
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_recipient_erasure import MessageRecipientErasure
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.services.suppression import ComplaintConfirmationRequired

# Mirrors PREFERENCES_TOKEN_MAX_AGE in nodejs/src/cdp/services/messaging/recipient-tokens.service.ts. Every link
# minted before an erase has expired once this much time has passed, so the erasure record is no longer needed.
PREFERENCE_LINK_MAX_AGE = timedelta(days=60)


@frozen
class ErasedRows:
    preferences: int
    suppressions: int


def erase_recipient(team_id: int, identifier: str, confirm_complaints: bool) -> ErasedRows:
    """Hard-delete every preference and suppression row the team holds for the address, in any case.

    Also records the erase, so preference links minted before it stop working. Raises
    `ComplaintConfirmationRequired`, and deletes nothing, when the address is suppressed for a spam complaint
    and `confirm_complaints` is false.
    """
    address = identifier.strip()
    with transaction.atomic():
        suppressions = MessageSuppression.objects.for_team(team_id)
        # The lock stops a complaint that lands during the check from being deleted unconfirmed. Only the locked
        # rows are deleted, so a row inserted after the check is left alone.
        locked = list(
            suppressions.filter(identifier=address.lower())
            .select_for_update()
            .values_list("id", "source", "suppressed", "deleted")
        )
        if not confirm_complaints and any(
            source == SuppressionSource.COMPLAINT and suppressed and not deleted
            for _, source, suppressed, deleted in locked
        ):
            raise ComplaintConfirmationRequired([address.lower()])

        suppressions_deleted, _ = suppressions.filter(id__in=[row_id for row_id, *_ in locked]).delete()
        preferences_deleted, _ = MessageRecipientPreference.objects.filter(
            team_id=team_id, identifier__iexact=address
        ).delete()
        MessageRecipientErasure.objects.update_or_create(
            team_id=team_id,
            identifier_hash=_identifier_hash(team_id, address),
            defaults={"erased_at": timezone.now()},
        )
    return ErasedRows(preferences=preferences_deleted, suppressions=suppressions_deleted)


def link_revoked(team_id: int, identifier: str, issued_at: datetime | None) -> bool:
    """Whether the team erased the address after the preference link was minted.

    A link with no issue time counts as revoked when the address was erased at all.
    """
    erasure = MessageRecipientErasure.objects.filter(
        team_id=team_id, identifier_hash=_identifier_hash(team_id, identifier.strip())
    ).first()
    if erasure is None:
        return False
    return issued_at is None or issued_at <= erasure.erased_at


def delete_expired_erasures() -> int:
    """Delete the erasure records that no live preference link can predate. Returns how many it deleted."""
    deleted, _ = MessageRecipientErasure.objects.filter(erased_at__lt=timezone.now() - PREFERENCE_LINK_MAX_AGE).delete()
    return deleted


def _identifier_hash(team_id: int, address: str) -> str:
    return hashlib.sha256(f"{team_id}:{address.lower()}".encode()).hexdigest()
