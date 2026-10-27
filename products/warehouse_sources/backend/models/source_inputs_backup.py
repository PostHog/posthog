from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel, sane_repr


class ExternalDataSourceInputsBackup(TeamScopedRootMixin, UUIDTModel):
    """An encrypted copy of the full `job_inputs` of a source, taken just before the strip removed its
    connection fields. The restore command reads it when the credentials row is lost. The prune command
    deletes it after the backup window.

    One backup per source, and a later strip never replaces it, so it always holds the first pre-strip value.
    No API, serializer or admin page shows this model.
    """

    # db_constraint=False: a FK constraint to posthog_team takes a lock on that hot table. Team scoping is
    # enforced by TeamScopedRootMixin.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # Not a FK, so that a hard delete of the source does not need to delete or wait for the backup.
    source_id = models.UUIDField(unique=True)
    source_type = models.CharField(max_length=128)
    inputs = EncryptedJSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "team_id", "source_id", "source_type")
