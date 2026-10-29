from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.workflows.backend.facade.enums import WorkflowImportSource


class WorkflowImport(TeamScopedRootMixin, UUIDModel):
    """A workflow imported from another messaging tool, with what the import could not carry over.

    The row ties the source object to its draft, so importing the same object again updates that draft
    instead of creating a second one. Only configuration is stored, never people.
    """

    Source = WorkflowImportSource

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "source", "source_id"], name="unique_workflow_import_source"),
        ]
        indexes = [models.Index(fields=["team", "hog_flow"], name="workflow_import_flow_idx")]

    # db_constraint=False: a real FK constraint to a hot table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    source = models.CharField(max_length=40, choices=Source.choices)
    source_id = models.CharField(max_length=200, help_text="The object's id in the source tool.")
    source_name = models.CharField(max_length=400, blank=True, default="")
    hog_flow = models.ForeignKey(
        "workflows.HogFlow", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.JSONField(
        default=list,
        blank=True,
        help_text="What the import changed or left out: a list of {level, message, step_id, step_name}.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    def __str__(self) -> str:
        return f"WorkflowImport {self.team_id}/{self.source}/{self.source_id}"
