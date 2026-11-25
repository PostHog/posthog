from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class MessageRecipientErasure(TeamScopedRootMixin, UUIDModel):
    """
    Records that a team erased a recipient, so preference links minted before the erase stop working.

    Opening a preference link recreates the recipient's preference row. Without this record, any link from an
    email sent before the erase would bring the erased address back. The record holds a hash of the address,
    not the address, and is deleted once every link minted before it has expired.
    """

    # db_constraint=False so CreateModel takes no lock on posthog_team (see HotTableAlterPolicy).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # SHA-256 hex digest of the team id and the lower-cased address.
    identifier_hash = models.CharField(max_length=64)
    erased_at = models.DateTimeField()

    class Meta:
        unique_together = ("team", "identifier_hash")
        db_table = "posthog_messagerecipienterasure"
        indexes = [models.Index(fields=["erased_at"], name="msg_erasure_erased_at")]

    def __str__(self) -> str:
        return f"Erasure {self.identifier_hash[:8]}"
