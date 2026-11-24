import uuid
from typing import ClassVar, Self

from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class PendingFileUpload(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    # The storage key keeps the original team ID even after the project is deleted.
    team_id = models.BigIntegerField()
    filename = models.TextField()
    expires_at = models.DateTimeField(db_index=True)
    objects: ClassVar[EnvironmentScopedManager[Self]] = EnvironmentScopedManager()
