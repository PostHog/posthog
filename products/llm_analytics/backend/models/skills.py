from django.db import models
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from posthog.models.utils import UUIDModel


class LLMSkill(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name", "version"],
                condition=Q(deleted=False),
                name="unique_llm_skill_version_per_team",
            ),
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=Q(deleted=False, is_latest=True),
                name="unique_llm_skill_latest_per_team",
            ),
        ]

    # Required by Agent Skills spec (https://agentskills.io/specification)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=4096)

    # The SKILL.md body content (markdown instructions)
    body = models.TextField()

    # Optional Agent Skills spec fields
    license = models.CharField(max_length=255, blank=True, default="")
    compatibility = models.CharField(max_length=500, blank=True, default="")
    allowed_tools = models.JSONField(blank=True, default=list)
    metadata = models.JSONField(blank=True, default=dict)

    # Versioning (same pattern as LLMPrompt)
    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    deleted = models.BooleanField(default=False)


class LLMSkillFile(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["skill", "path"],
                name="unique_skill_file_path",
            ),
        ]

    skill = models.ForeignKey(LLMSkill, on_delete=models.CASCADE, related_name="files")
    path = models.CharField(max_length=500)
    content = models.TextField()
    content_type = models.CharField(max_length=100, default="text/plain")


def annotate_llm_skill_version_history_metadata(queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
    active_versions = LLMSkill.objects.filter(team_id=OuterRef("team_id"), name=OuterRef("name"), deleted=False)

    version_count = Subquery(
        active_versions.values("name").annotate(count=Count("id")).values("count")[:1],
        output_field=IntegerField(),
    )
    latest_version = Subquery(
        active_versions.order_by("-version", "-created_at", "-id").values("version")[:1],
        output_field=IntegerField(),
    )
    first_version_created_at = Subquery(
        active_versions.filter(version=1).order_by("created_at", "id").values("created_at")[:1],
        output_field=DateTimeField(),
    )
    return queryset.annotate(
        version_count=version_count,
        latest_version=latest_version,
        first_version_created_at=first_version_created_at,
    )
