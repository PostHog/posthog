import re
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TypeVar

from django.db import connection, router, transaction
from django.db.models import F, Func, Value
from django.db.models.functions import Lower
from django.utils import timezone

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_recipient_erasure import MessageRecipientErasure
from products.messaging.backend.services.suppression import hard_delete_suppressions

# Mirrors PREFERENCES_TOKEN_MAX_AGE in nodejs/src/cdp/services/messaging/recipient-tokens.service.ts. Every link
# minted before an erase has expired once this much time has passed, so the erasure record is no longer needed.
PREFERENCE_LINK_MAX_AGE = timedelta(days=60)

# The ASCII whitespace that PostgreSQL's [[:space:]] class matches, so Python and SQL trim the same characters.
_SURROUNDING_WHITESPACE = re.compile(r"^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$")
_SQL_SURROUNDING_WHITESPACE = r"^[[:space:]]+|[[:space:]]+$"

T = TypeVar("T")


@frozen
class ErasedRecipient:
    preferences_deleted: int
    suppressions_deleted: int


class PreferenceLinkRevoked(Exception):
    """The team erased the link's recipient after the link was minted."""


def erase_recipient(team_id: int, identifier: str, confirm_complaints: bool) -> ErasedRecipient:
    """Hard-delete every preference and suppression row the team holds for the address, ignoring case and
    surrounding whitespace.

    Also records the erase, so preference links minted before it stop working. Raises
    `ComplaintConfirmationRequired`, and deletes nothing, when the address is suppressed for a spam complaint
    and `confirm_complaints` is false.
    """
    address = _normalized(identifier)
    with _recipient_lock(team_id, address):
        suppressions_deleted = hard_delete_suppressions(team_id, address, confirm_complaints)
        normalized_identifier = Lower(
            Func(F("identifier"), Value(_SQL_SURROUNDING_WHITESPACE), Value(""), Value("g"), function="REGEXP_REPLACE")
        )
        preferences_deleted, _ = (
            MessageRecipientPreference.objects.filter(team_id=team_id)
            .annotate(normalized_identifier=normalized_identifier)
            .filter(normalized_identifier=address)
            .delete()
        )
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
    address = _normalized(identifier)
    with _recipient_lock(team_id, address):
        # Read the primary, where the lock is held: a replica can lag behind an erase that just committed.
        erasure = (
            MessageRecipientErasure.objects.db_manager(router.db_for_write(MessageRecipientErasure))
            .for_team(team_id)
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


def _normalized(identifier: str) -> str:
    return _SURROUNDING_WHITESPACE.sub("", identifier).lower()


def _identifier_hash(team_id: int, address: str) -> str:
    return hashlib.sha256(f"{team_id}:{address}".encode()).hexdigest()
