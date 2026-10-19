"""Django models for research_desk."""

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import SessionOrigin, SessionStatus, SourceKind, SourceOrigin


class ResearchSource(ProductTeamModel):
    """A recruiting channel whose existing events count as research touches.

    The contact check reads touches in place from the events each source already emits,
    so registering a source copies no data.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    kind = models.CharField(max_length=32, choices=SourceKind.choices)
    # Workflow ID, survey ID, cohort ID or event name, depending on kind.
    external_id = models.CharField(max_length=400)
    label = models.CharField(max_length=255)
    owner_email = models.EmailField(blank=True, default="")
    product_area = models.CharField(max_length=128, blank=True, default="")
    origin = models.CharField(max_length=32, choices=SourceOrigin.choices, default=SourceOrigin.MANUAL.value)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "kind", "external_id"], name="research_desk_source_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.label}"


class ResearchSession(ProductTeamModel):
    """A conversation with one or more customers, detected by a scout or logged by hand."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    origin = models.CharField(max_length=32, choices=SessionOrigin.choices)
    # Stable identity from the origin, such as a calendar event UID, so scouts can upsert.
    external_ref = models.CharField(max_length=512)
    title = models.CharField(max_length=512, blank=True, default="")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED.value)
    organizer_email = models.EmailField(blank=True, default="")
    internal_emails = ArrayField(models.CharField(max_length=254), default=list, blank=True)
    external_emails = ArrayField(models.CharField(max_length=254), default=list, blank=True)
    # Lowercased domains of external_emails, so org-level checks can use the GIN index.
    external_domains = ArrayField(models.CharField(max_length=254), default=list, blank=True)
    meeting_url = models.URLField(max_length=2048, blank=True, default="")
    brief_posted_at = models.DateTimeField(null=True, blank=True)
    slack_message_ts = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "origin", "external_ref"], name="research_desk_session_unique"),
        ]
        indexes = [
            models.Index(fields=["team_id", "-start_time"], name="research_desk_session_start"),
            GinIndex(fields=["external_emails"], name="research_desk_session_emails"),
            GinIndex(fields=["external_domains"], name="research_desk_session_domains"),
        ]

    def __str__(self) -> str:
        return self.title or self.external_ref
