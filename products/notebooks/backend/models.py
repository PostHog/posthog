from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField, QuerySet
from django.utils import timezone

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.team import Team
from posthog.models.utils import (
    RootTeamMixin,
    UUIDTModel,
    build_partial_uniqueness_constraint,
    build_unique_relationship_check,
)
from posthog.utils import generate_short_id


class Notebook(FileSystemSyncMixin, RootTeamMixin, UUIDTModel):
    class Visibility(models.TextChoices):
        INTERNAL = "internal", "internal"
        DEFAULT = "default", "default"

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=256, blank=True, null=True)
    content: JSONField = JSONField(default=None, null=True, blank=True)
    text_content = models.TextField(blank=True, null=True)
    deleted = models.BooleanField(default=False)
    visibility = models.CharField(choices=Visibility.choices, default=Visibility.DEFAULT, max_length=20)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_notebooks",
    )

    class Meta:
        unique_together = ("team", "short_id")
        db_table = "posthog_notebook"

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Notebook"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="notebook", ref_field="short_id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Notebooks"),
            type="notebook",  # sync with APIScopeObject in scopes.py
            ref=str(self.short_id),
            name=self.title or "Untitled",
            href=f"/notebooks/{self.short_id}",
            meta={"created_at": str(self.created_at), "created_by": self.created_by_id},
            should_delete=self.deleted or self.visibility == self.Visibility.INTERNAL,
        )


RELATED_OBJECTS = ("group",)


class ResourceNotebook(UUIDTModel):
    """
    Generic relationship table linking notebooks to various resources.
    This allows notebooks to be associated with multiple models.

    Uses explicit foreign keys rather than GenericForeignKey for better performance
    and type safety.
    """

    notebook = models.ForeignKey("notebooks.Notebook", on_delete=models.CASCADE, related_name="resources")

    # Relationships (exactly one must be set)
    # When adding a new foreign key, make sure to add the foreign key field and append field name
    # to the `RELATED_OBJECTS` tuple above.
    # Group relationship is not a foreign key because the table lives in another database instance, which would cause IntegrityErrors when inserting a new ResourceNotebook row.

    group = models.IntegerField(
        null=True,
        blank=True,
        db_column="group_id",
    )

    class Meta:
        unique_together = ("notebook", *RELATED_OBJECTS)
        constraints = [
            *[
                build_partial_uniqueness_constraint(
                    field="notebook",
                    related_field=related_field,
                    constraint_name=f"unique_notebook_{related_field}",
                )
                for related_field in RELATED_OBJECTS
            ],
            models.CheckConstraint(
                check=build_unique_relationship_check(RELATED_OBJECTS), name="exactly_one_notebook_related_resource"
            ),
        ]
        db_table = "posthog_resourcenotebook"

    def clean(self):
        super().clean()
        """Ensure that exactly one resource field is set."""
        if sum(map(bool, [getattr(self, field) for field in RELATED_OBJECTS])) != 1:
            raise ValidationError("Exactly one resource field must be set.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def resource_type(self) -> str:
        """Return the type of the related resource."""
        for field in RELATED_OBJECTS:
            if getattr(self, field):
                return field
        return "unknown"

    @property
    def resource(self):
        """Return the actual related resource object."""
        resource_type = self.resource_type
        if resource_type != "unknown":
            return getattr(self, resource_type)
        return None

    def __str__(self) -> str:
        return f"Notebook {self.notebook.short_id} -> {self.resource_type} {self.resource}"
