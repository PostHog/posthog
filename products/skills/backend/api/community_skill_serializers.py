from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillTrustTier

ALLOWED_LIST_ORDERINGS = frozenset(
    {
        "name",
        "-name",
        "created_at",
        "-created_at",
        "published_at",
        "-published_at",
        "install_count",
        "-install_count",
        "vote_count",
        "-vote_count",
    }
)


class CommunitySkillFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunitySkillFile
        fields = ["path", "content", "content_type"]


class CommunitySkillFileManifestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunitySkillFile
        fields = ["path", "content_type"]


class CommunitySkillSerializer(serializers.ModelSerializer):
    allowed_tools = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Tools the skill declares it may use. Surface these to the user before install.",
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text="Arbitrary key-value metadata carried from the skill's frontmatter.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Free-form tags used for filtering and discovery.",
    )
    trust_tier = serializers.ChoiceField(
        choices=CommunitySkillTrustTier.choices,
        help_text="Moderation tier: 'official' (PostHog-authored), 'verified' (reviewed), or 'community'.",
    )
    files = serializers.SerializerMethodField(
        help_text=(
            "Bundled files manifest (path + content_type only). Fetch full content via the skill detail endpoint."
        ),
    )
    vote_count = serializers.SerializerMethodField(
        help_text="Total number of upvotes this skill has received.",
    )
    has_voted = serializers.SerializerMethodField(
        help_text="Whether the requesting user has upvoted this skill.",
    )

    class Meta:
        model = CommunitySkill
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "body",
            "license",
            "compatibility",
            "allowed_tools",
            "metadata",
            "tags",
            "trust_tier",
            "author_handle",
            "github_url",
            "files",
            "install_count",
            "vote_count",
            "has_voted",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "slug": {"help_text": "Stable identifier matching the skill's directory in the community-skills repo."},
            "name": {"help_text": "Display name of the skill."},
            "description": {"help_text": "What the skill does and when to use it."},
            "body": {"help_text": "The SKILL.md instruction content (markdown)."},
            "license": {"help_text": "License name or reference."},
            "compatibility": {"help_text": "Environment requirements declared by the skill."},
            "author_handle": {"help_text": "GitHub handle (or name) of the contributor who published the skill."},
            "github_url": {"help_text": "Link to the skill's source directory on GitHub."},
            "install_count": {"help_text": "Number of times this skill has been installed into a team."},
            "published_at": {"help_text": "When the skill was first published to the community repo."},
        }

    @extend_schema_field(CommunitySkillFileManifestSerializer(many=True))
    def get_files(self, instance: CommunitySkill) -> list[dict[str, Any]]:
        return [dict(row) for row in instance.files.values("path", "content_type")]

    def get_vote_count(self, instance: CommunitySkill) -> int:
        # Provided by the viewset's annotated queryset; fall back to a count for unannotated instances.
        annotated = getattr(instance, "vote_count", None)
        return int(annotated) if annotated is not None else instance.votes.count()

    def get_has_voted(self, instance: CommunitySkill) -> bool:
        return bool(getattr(instance, "has_voted", False))


class CommunitySkillListSerializer(CommunitySkillSerializer):
    """List serializer that omits body and file manifest — progressive disclosure."""

    class Meta(CommunitySkillSerializer.Meta):
        fields = [f for f in CommunitySkillSerializer.Meta.fields if f not in ("body", "files")]
        read_only_fields = fields


class CommunitySkillListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Substring filter applied to skill names, descriptions, and tags.",
    )
    tag = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Return only skills carrying this tag.",
    )
    trust_tier = serializers.ChoiceField(
        choices=CommunitySkillTrustTier.choices,
        required=False,
        help_text="Filter to a single moderation tier.",
    )
    order_by = serializers.ChoiceField(
        choices=sorted(ALLOWED_LIST_ORDERINGS),
        required=False,
        default="-install_count",
        help_text="Sort key. Defaults to most-installed first.",
    )


class CommunitySkillInstallSerializer(serializers.Serializer):
    new_name = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Name for the installed skill in your team. Defaults to the community skill's slug.",
    )


class CommunitySkillVoteResponseSerializer(serializers.Serializer):
    vote_count = serializers.IntegerField(help_text="Total upvotes after applying the toggle.")
    has_voted = serializers.BooleanField(help_text="Whether the requesting user is now an upvoter.")
