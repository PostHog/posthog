from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDTModel, sane_repr

from products.warehouse_sources.backend.types import ExternalDataSourceType

PENDING_CREDENTIAL_TTL = timedelta(hours=24)


def pending_credential_default_expiry() -> datetime:
    return timezone.now() + PENDING_CREDENTIAL_TTL


class PendingSourceCredential(TeamScopedRootMixin, CreatedMetaFields, UUIDTModel):
    """Temporary stash for source credentials collected via the source connect page.

    Credentials are validated against a live connection, stored encrypted, and referenced by id when
    creating the source (so secrets never pass through an agent conversation). Rows are deleted as
    soon as the source is created, and ignored/purged after `expires_at` if never consumed.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source_type = models.CharField(max_length=128, choices=ExternalDataSourceType)
    payload = EncryptedJSONField(default=dict)
    expires_at = models.DateTimeField(default=pending_credential_default_expiry)

    __repr__ = sane_repr("id", "team_id", "source_type")
