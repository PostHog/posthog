from collections.abc import Collection
from typing import Any, Self

from django.db import models
from django.db.models import QuerySet

from posthog.models.file_system.constants import (
    DEFAULT_SURFACE,
    resolved_workflows_list_v2_answer,
    workflows_list_v2_enabled,
)
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.tagged_items_relation import Taggable
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel

KEY_CONSTRAINT = "unique_message_template_key_per_team"


# nosemgrep: no-new-uuidt-models -- an existing model, and its stored ids cannot change.
class MessageTemplate(FileSystemSyncMixin, Taggable, UUIDTModel):
    """
    A model for storing message templates used for email and eventually other messaging channels.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    message_category = models.ForeignKey("messaging.MessageCategory", on_delete=models.SET_NULL, null=True, blank=True)
    content = models.JSONField(default=dict)
    type = models.CharField(max_length=24, blank=True, default="email")
    deleted = models.BooleanField(default=False)
    # Set once the template is made transactional: the workflow the send API runs for it. A plain id,
    # because the workflow lives in the workflows product.
    transactional_hog_flow_id = models.UUIDField(null=True, blank=True)
    # Unpublished edits to a transactional template. Sends keep using `content` until the draft is published.
    draft_content = models.JSONField(null=True, blank=True)
    # For emails carrying codes or reset links: sends keep no rendered body or subject, and clicks keep only
    # the link's origin.
    sensitive = models.BooleanField(default=False, db_default=False)
    key = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="Client-chosen identifier, unique within this environment among templates that are not deleted. "
        "Letters, numbers, hyphens (-) and underscores (_) only.",
    )

    class Meta:
        db_table = "posthog_messagetemplate"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "key"],
                condition=models.Q(key__isnull=False, deleted=False),
                name=KEY_CONSTRAINT,
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get_file_system_unfiled(cls, team: Team, surface: str = DEFAULT_SURFACE) -> QuerySet["MessageTemplate"]:
        return cls._filter_unfiled_queryset(
            cls.objects.filter(team=team, deleted=False).only(
                "id", "team_id", "name", "created_at", "created_by_id", "deleted"
            ),
            team,
            type="message_template",
            ref_field="id",
            surface=surface,
        )

    @classmethod
    def from_db(cls, db: str | None, field_names: Collection[str], values: Collection[Any], **kwargs: Any) -> Self:
        instance = super().from_db(db, field_names, values, **kwargs)
        instance._stored_name = instance.__dict__.get("name")
        return instance

    def sync_file_system(self) -> None:
        # A file can carry a name of its own, and renaming it needs editor access to workflows. A save that
        # keeps the stored name, such as a description or design edit, must not reset that file name, so it
        # leaves existing files alone. A rename passes the same access check before the save.
        keeps_files = (
            not self.deleted
            and not isinstance(self._create_in_folder, str)
            and self.__dict__.get("name") == getattr(self, "_stored_name", None)
        )
        if not keeps_files or not self._has_file_system_row(self.team, self.get_file_system_representation()):
            super().sync_file_system()
        self._stored_name = self.__dict__.get("name")

    def files_new_rows(self) -> bool:
        if self.created_by_id is None:
            return False
        resolved = resolved_workflows_list_v2_answer(self.team_id, self.created_by_id)
        if resolved is not None:
            return resolved
        return self.created_by is not None and workflows_list_v2_enabled(self.team, self.created_by)

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Email templates"),
            type="message_template",
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/workflows/library/templates/{self.id}",
            meta={"created_at": str(self.created_at), "created_by": self.created_by_id},
            should_delete=self.deleted,
        )
