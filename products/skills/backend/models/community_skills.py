from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class CommunitySkillTrustTier(models.TextChoices):
    OFFICIAL = "official", "Official"
    VERIFIED = "verified", "Verified"
    COMMUNITY = "community", "Community"


class CommunitySkill(UUIDModel):
    """Instance-global catalog of community-shared agent skills.

    The source of truth for skill content is the PostHog/community-skills GitHub repo;
    rows here are a synced read-model that powers in-app discovery, search, ranking, and
    install. This model is deliberately NOT team-scoped — it is shared catalog data (the
    same way DashboardTemplate GLOBAL templates are), so it has no team_id by design.
    Installing a community skill copies it into a team as a regular LLMSkill.
    """

    class Meta:
        db_table = "llm_analytics_communityskill"

    # The repo directory name — the stable, human-readable identifier used in URLs.
    slug = models.CharField(max_length=64, unique=True)

    # Mirrors the Agent Skills spec fields carried by LLMSkill.
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=4096)
    body = models.TextField()
    license = models.CharField(max_length=255, blank=True, default="")
    compatibility = models.CharField(max_length=500, blank=True, default="")
    allowed_tools = models.JSONField(blank=True, default=list)
    metadata = models.JSONField(blank=True, default=dict)

    # Marketplace fields.
    tags = models.JSONField(blank=True, default=list)
    trust_tier = models.CharField(
        max_length=20,
        choices=CommunitySkillTrustTier.choices,
        default=CommunitySkillTrustTier.COMMUNITY,
    )
    author_handle = models.CharField(max_length=255, blank=True, default="")
    github_url = models.CharField(max_length=8201, blank=True, default="")
    # Commit SHA of the repo state this row was last synced from — lets the sync job skip unchanged skills.
    source_sha = models.CharField(max_length=64, blank=True, default="")
    # Denormalized install counter, incremented on each install. Strongest popularity signal.
    install_count = models.PositiveIntegerField(default=0)

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # Soft-delete for skills removed from the repo, so install history and votes survive.
    deleted = models.BooleanField(default=False)


class CommunitySkillFile(UUIDModel):
    class Meta:
        db_table = "llm_analytics_communityskillfile"
        constraints = [
            models.UniqueConstraint(
                fields=["skill", "path"],
                name="unique_community_skill_file_path",
            ),
        ]

    skill = models.ForeignKey(CommunitySkill, on_delete=models.CASCADE, related_name="files")
    path = models.CharField(max_length=500)
    content = models.TextField()
    content_type = models.CharField(max_length=100, default="text/plain")


class CommunitySkillVote(UUIDModel):
    """A single user's upvote of a community skill. User-scoped, not tenant data."""

    class Meta:
        db_table = "llm_analytics_communityskillvote"
        constraints = [
            models.UniqueConstraint(
                fields=["skill", "user"],
                name="unique_community_skill_vote_per_user",
            ),
        ]

    skill = models.ForeignKey(CommunitySkill, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
