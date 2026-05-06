from __future__ import annotations

from typing import Any

from django.db import models, transaction

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class ScoreDefinition(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Kind(models.TextChoices):
        CATEGORICAL = "categorical", "categorical"
        NUMERIC = "numeric", "numeric"
        BOOLEAN = "boolean", "boolean"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=32, choices=Kind)
    archived = models.BooleanField(default=False)
    current_version = models.ForeignKey(
        "ScoreDefinitionVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["team", "kind", "archived"], name="llma_score_def_team_kind_idx")]

    @transaction.atomic
    def create_new_version(self, *, config: dict[str, Any], created_by: User | None) -> ScoreDefinitionVersion:
        definition = ScoreDefinition.objects.select_for_update().get(pk=self.pk)
        current_version_number = (
            ScoreDefinitionVersion.objects.only("version").get(pk=definition.current_version_id).version
            if definition.current_version_id is not None
            else 0
        )

        version = ScoreDefinitionVersion.objects.create(
            definition=definition,
            version=current_version_number + 1,
            config=config,
            created_by=created_by,
        )

        definition.current_version = version
        definition.save(update_fields=["current_version", "updated_at"])

        self.current_version = version
        return version


class ScoreDefinitionVersion(UUIDModel, CreatedMetaFields):
    definition = models.ForeignKey(ScoreDefinition, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    config = models.JSONField(default=dict)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version"],
                name="uniq_llma_score_def_ver",
            )
        ]
        indexes = [
            models.Index(fields=["definition", "-version"], name="llma_score_def_ver_def_idx"),
            models.Index(fields=["created_at"], name="llma_score_def_ver_created_idx"),
        ]
