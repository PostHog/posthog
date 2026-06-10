from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class ToolbarAnnotation(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """
    A UI annotation captured from the PostHog toolbar on a user's own site.

    The user points at an element, leaves a comment, and the toolbar records the
    element selector plus page context. Annotations are surfaced over MCP so a
    coding agent can pick them up and turn them into changes, then mark them resolved.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    comment = models.TextField(help_text="The annotation note the user wrote about the element.")
    # Field named `annotation_status` (not `status`) to avoid a drf-spectacular enum-name collision.
    annotation_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Lifecycle of the annotation as an agent works through it.",
    )
    resolution = models.TextField(
        null=True,
        blank=True,
        help_text="Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.",
    )

    # Page context — where the annotation was made.
    url = models.TextField(help_text="Full URL of the page the annotation was made on.")
    host = models.CharField(
        max_length=255,
        help_text="Hostname of the page (e.g. app.example.com), used to scope annotations to a site.",
    )
    pathname = models.TextField(null=True, blank=True, help_text="Path portion of the URL.")

    # Element context — what the user pointed at.
    selector = models.TextField(help_text="CSS selector that locates the annotated element on the page.")
    element_text = models.TextField(null=True, blank=True, help_text="Visible text of the annotated element, if any.")
    element_chain = models.TextField(
        null=True,
        blank=True,
        help_text="Serialized autocapture-style element chain from the element up to the document root.",
    )
    element_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured element metadata (inferred selectors, attributes, component hints).",
    )
    viewport = models.JSONField(
        null=True,
        blank=True,
        help_text="Viewport size when the annotation was made, as {width, height} in pixels.",
    )
    screenshot_url = models.TextField(
        null=True, blank=True, help_text="URL of an uploaded screenshot captured with the annotation."
    )

    class Meta:
        db_table = "posthog_toolbar_annotation"
        indexes = [
            models.Index(fields=["team_id", "annotation_status"], name="toolbar_annot_team_status_idx"),
            models.Index(fields=["team_id", "host"], name="toolbar_annot_team_host_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id} @ {self.host}: {self.comment[:40]}"
