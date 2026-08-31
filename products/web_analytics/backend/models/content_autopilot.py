from collections.abc import Iterable

from django.db import models
from django.db.models.base import ModelBase

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


def default_content_autopilot_package() -> dict[str, object]:
    return {
        "file_path": "",
        "title": "",
        "description": "",
        "slug": "",
        "frontmatter": [],
        "internal_links": [],
        "source_notes": [],
    }


def default_content_autopilot_validation_report() -> dict[str, object]:
    return {"passed": False, "checks": []}


class ContentAutopilotSiteProfile(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    domain = models.URLField(max_length=2048)
    source_urls = models.JSONField(default=list)
    content_boundaries = models.JSONField(default=list)
    brand_rules = models.JSONField(default=list)
    search_console_enabled = models.BooleanField(default=False)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_contentautopilotsiteprofile"
        constraints = [
            models.UniqueConstraint(fields=["team", "domain"], name="content_auto_profile_team_domain"),
        ]


class ContentAutopilotRun(TeamScopedRootMixin, UUIDModel):
    class RunStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        FAILED = "failed", "Failed"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    profile = models.ForeignKey(ContentAutopilotSiteProfile, on_delete=models.CASCADE, related_name="runs")
    run_status = models.CharField(max_length=32, choices=RunStatus.choices, default=RunStatus.PENDING)
    input_snapshot = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    triggered_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_contentautopilotrun"
        indexes = [models.Index(fields=["team", "-created_at"], name="content_auto_run_team_created")]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        profile_team_id = self.profile.team_id
        if self.team_id is not None and self.team_id != profile_team_id:
            raise ValueError("ContentAutopilotRun must belong to the same team as its profile.")
        self.team_id = profile_team_id
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class ContentAutopilotProposal(TeamScopedRootMixin, UUIDModel):
    class ProposalType(models.TextChoices):
        NEW_CONTENT = "new_content", "New content"
        PAGE_IMPROVEMENT = "page_improvement", "Page improvement"

    class LifecycleStatus(models.TextChoices):
        GENERATING = "generating", "Generating"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        REJECTED = "rejected", "Rejected"
        EXPORTED = "exported", "Exported"
        FAILED = "failed", "Failed"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    run = models.ForeignKey(ContentAutopilotRun, on_delete=models.CASCADE, related_name="proposals")
    proposal_type = models.CharField(max_length=32, choices=ProposalType.choices)
    lifecycle_status = models.CharField(
        max_length=32,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.GENERATING,
    )
    title = models.CharField(max_length=512)
    target_query = models.CharField(max_length=512, blank=True, default="")
    target_url = models.URLField(max_length=2048, blank=True, default="")
    evidence = models.JSONField(default=list)
    validation_report = models.JSONField(default=default_content_autopilot_validation_report)
    content_package = models.JSONField(default=default_content_autopilot_package)
    original_markdown = models.TextField(blank=True, default="")
    proposed_markdown = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_contentautopilotproposal"
        indexes = [
            models.Index(fields=["team", "lifecycle_status", "-created_at"], name="content_auto_prop_status"),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        run_team_id = self.run.team_id
        if self.team_id is not None and self.team_id != run_team_id:
            raise ValueError("ContentAutopilotProposal must belong to the same team as its run.")
        self.team_id = run_team_id
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )
