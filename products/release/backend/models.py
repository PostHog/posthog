"""
Django models for release.

Keep models thin — business logic belongs in logic/.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import uuid7


class Release(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    feature_flag_ids = ArrayField(models.IntegerField(), default=list, blank=True)
    broadcast_ids = ArrayField(models.UUIDField(), default=list, blank=True, db_default=[])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["team", "created_at", "id"], name="release_team_created_idx")]

    def __str__(self) -> str:
        return self.name
