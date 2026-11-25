import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TypeVar

from django.db import connection, transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_recipient_erasure import MessageRecipientErasure
from products.messaging.backend.models.message_suppression import MessageSuppression
from products.messaging.backend.services.suppression import lock_confirming_complaints

# Mirrors PREFERENCES_TOKEN_MAX_AGE in nodejs/src/cdp/services/messaging/recipient-tokens.service.ts. Every link
# minted before an erase has expired once this much time has passed, so the erasure record is no longer needed.
PREFERENCE_LINK_MAX_AGE = timedelta(days=60)

T = TypeVar("T")


@frozen
class ErasedRecipient:
    preferences_deleted: int
    suppressions_deleted: int


class PreferenceLinkRevoked(Exception):
    """The team erased the link's recipient after the link was minted."""


def erase_recipient(team_id: int, identifier: str, confirm_complaints: bool) -> ErasedRecipient:
    """Hard-delete every preference and suppression row the team holds for the address, in any case.

    Also records the erase, so preference links minted before it stop working. Raises
    `ComplaintConfirmationRequired`, and deletes nothing, when the address is suppressed for a spam complaint
    and `confirm_complaints` is false.
    """
    address = identifier.strip()
    with _recipient_lock(team_id, address):
        suppressions = MessageSuppression.objects.for_team(team_id)
        locked = lock_confirming_complaints(suppressions.filter(identifier=address.lower()), confirm_complaints)
        suppressions_deleted, _ = suppressions.filter(id__in=[row.id for row in locked]).delete()
        preferences_deleted, _ = MessageRecipientPreference.objects.filter(
            team_id=team_id, identifier__iexact=address
        ).delete()
        MessageRecipientErasure.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            identifier_hash=_identifier_hash(team_id, address),
            defaults={"erased_at": timezone.now()},
        )
    return ErasedRecipient(preferences_deleted=preferences_deleted, suppressions_deleted=suppressions_deleted)


def write_through_link(team_id: int, identifier: str, issued_at: datetime | None, write: Callable[[], T]) -> T:
    """Run a preference write that a preference link asked for, unless the team erased the address after the link
    was minted. A link with no issue time counts as minted before any erase.

    Raises `PreferenceLinkRevoked`, and writes nothing, for a revoked link. The write holds the same lock as an
    erase, so an erase can't land between the check and the write.
    """
    address = identifier.strip()
    with _recipient_lock(team_id, address):
        erasure = (
            MessageRecipientErasure.objects.for_team(team_id)
            .filter(identifier_hash=_identifier_hash(team_id, address))
            .first()
        )
        if erasure is not None and (issued_at is None or issued_at <= erasure.erased_at):
            raise PreferenceLinkRevoked()
        return write()


@contextmanager
def _recipient_lock(team_id: int, address: str) -> Iterator[None]:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"message-recipient:{_identifier_hash(team_id, address)}"],
            )
        yield


def _identifier_hash(team_id: int, address: str) -> str:
    return hashlib.sha256(f"{team_id}:{address.lower()}".encode()).hexdigest()
