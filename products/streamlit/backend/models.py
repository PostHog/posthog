from typing import TYPE_CHECKING

from django.db import models
from django.db.models import QuerySet

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import RootTeamMixin, UUIDTModel, sane_repr

if TYPE_CHECKING:
    from posthog.models.team import Team


class StreamlitApp(FileSystemSyncMixin, RootTeamMixin, UUIDTModel):
    class Meta:
        db_table = "posthog_streamlitapp"
        managed = True

    class ContainerStatus(models.TextChoices):
        PENDING = "pending", "pending"
        RUNNING = "running", "running"
        STOPPED = "stopped", "stopped"
        FAILED = "failed", "failed"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="streamlit_apps",
        related_query_name="streamlit_app",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    container_id = models.CharField(max_length=200, blank=True)
    container_status = models.CharField(
        max_length=20,
        choices=ContainerStatus.choices,
        default=ContainerStatus.PENDING,
    )
    port = models.IntegerField(null=True, blank=True, help_text="Port assigned to the container")
    internal_url = models.CharField(
        max_length=500, 
        blank=True, 
        help_text="Internal URL for container access"
    )
    public_url = models.CharField(
        max_length=500, 
        blank=True, 
        help_text="Public URL for accessing the app"
    )
    last_accessed = models.DateTimeField(null=True, blank=True)
    
    # File upload fields
    entrypoint_file = models.FileField(
        upload_to="streamlit_apps/entrypoints/",
        blank=True,
        null=True,
        help_text="Main Python file for the Streamlit app"
    )
    requirements_file = models.FileField(
        upload_to="streamlit_apps/requirements/",
        blank=True,
        null=True,
        help_text="Requirements.txt file for Python dependencies"
    )
    app_type = models.CharField(
        max_length=20,
        choices=[
            ("default", "Default Hello World"),
            ("custom", "Custom Uploaded App"),
        ],
        default="default",
        help_text="Type of Streamlit app"
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="created_streamlit_apps",
        related_query_name="created_streamlit_app",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    __repr__ = sane_repr("id", "name", "team_id", "container_status")

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["StreamlitApp"]:
        base_qs = cls.objects.filter(team=team)
        return cls._filter_unfiled_queryset(base_qs, team, type="streamlit_app", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Streamlit Apps"),
            type="streamlit_app",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/streamlit_apps/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": None,
            },
            should_delete=False,
        )
