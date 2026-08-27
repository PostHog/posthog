"""Django models for metrics."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import QuerySet

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.file_system.constants import DEFAULT_SURFACE
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.metrics.backend.pipeline_config import parse_pipeline_config


class MetricsPipeline(
    FileSystemSyncMixin, ModelActivityMixin, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel
):
    """A saved pipeline topology: nodes (components with health stats) and
    edges (throughput flows), stored as one validated JSON config.

    The graph invariants live in `parse_pipeline_config`. The facade validates
    against it on every write, which is what actually protects the stored
    config; `clean()` delegates to the same parser so a `full_clean()` caller
    (a ModelForm, the admin) gets the identical errors."""

    # db_constraint=False on the hot-table FKs (team, created_by) keeps the
    # CreateModel migration from taking a lock on posthog_team/posthog_user.
    team = models.ForeignKey(Team, on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    config = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        try:
            parse_pipeline_config(self.config)
        except ValueError as e:
            raise ValidationError({"config": str(e)}) from e

    @classmethod
    def get_file_system_unfiled(cls, team: Team, surface: str = DEFAULT_SURFACE) -> QuerySet["MetricsPipeline"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="metrics_pipeline", ref_field="id", surface=surface)

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Pipelines"),
            type="metrics_pipeline",
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/metrics/pipelines/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=self.deleted,
        )
