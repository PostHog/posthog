from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillKind, CommunitySkillTrustTier
from .community_scout_config import (
    MAX_CRON_SCHEDULE_LENGTH,
    MAX_RUN_INTERVAL_MINUTES,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    MIN_RUN_INTERVAL_MINUTES,
)
from .skill_template_services import parse_template_variables

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


class CommunitySkillScoutConfigSerializer(serializers.Serializer):
    """The scout settings a published scout travels with. Every field is optional. An omitted field
    means the scout-create form's own default applies."""

    run_interval_minutes = serializers.IntegerField(
        required=False,
        min_value=MIN_RUN_INTERVAL_MINUTES,
        max_value=MAX_RUN_INTERVAL_MINUTES,
        help_text="How often the scout runs, in minutes. Ignored when run_cron_schedule is set.",
    )
    run_cron_schedule = serializers.CharField(
        required=False,
        max_length=MAX_CRON_SCHEDULE_LENGTH,
        help_text="Five-field cron expression for the scout's schedule, which takes precedence over the interval.",
    )
    emit = serializers.BooleanField(
        required=False,
        help_text="Whether the scout writes its reports to the inbox. False means it runs as a dry run.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=MAX_TAG_LENGTH),
        required=False,
        max_length=MAX_TAGS,
        help_text="Tags used to group the scout in the fleet.",
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise serializers.ValidationError(dict.fromkeys(unknown, "This scout setting is not supported."))
        return super().to_internal_value(data)


class CommunitySkillTemplateVariableSerializer(serializers.Serializer):
    """One declared variable of a templated skill — the schema a client renders a form from."""

    name = serializers.CharField(help_text="Variable identifier, substituted for `{{ name }}` in the skill body.")
    prompt = serializers.CharField(
        allow_blank=True,
        help_text="Human-readable question shown when collecting a value for this variable.",
    )
    is_required = serializers.BooleanField(
        help_text="Whether a value must be supplied at install time (otherwise it falls back to the default).",
    )
    default = serializers.CharField(
        allow_blank=True,
        help_text="Value used when none is supplied. Empty when the variable has no default.",
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
    kind = serializers.ChoiceField(
        choices=CommunitySkillKind.choices,
        help_text=(
            "'skill' installs into the project as a regular skill. 'scout' runs on a schedule, so it is set up "
            "through the scout form instead of being installed."
        ),
    )
    scout_config = CommunitySkillScoutConfigSerializer(
        help_text="Schedule, emit posture and tags a scout travels with. Empty object for a skill.",
    )
    files = serializers.SerializerMethodField(
        help_text="Bundled files manifest — path and content_type only. File contents are copied in on install.",
    )
    template_variables = serializers.SerializerMethodField(
        help_text=(
            "Declared template variables, parsed from metadata. Non-empty marks this skill as a template: "
            "collect a value for each and pass them as `variables` when installing."
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
            "kind",
            "scout_config",
            "author_handle",
            "github_url",
            "files",
            "template_variables",
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
        # Iterate the related manager so prefetch_related's cache is used — .values() would issue a
        # second query and defeat the viewset's manifest-only prefetch.
        return [{"path": f.path, "content_type": f.content_type} for f in instance.files.all()]

    @extend_schema_field(CommunitySkillTemplateVariableSerializer(many=True))
    def get_template_variables(self, instance: CommunitySkill) -> list[dict[str, Any]]:
        return [
            {"name": v.name, "prompt": v.prompt, "is_required": v.required, "default": v.default}
            for v in parse_template_variables(instance.metadata)
        ]

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
        help_text="Substring filter on skill names and descriptions; also matches a tag exactly (case-insensitive).",
    )
    tag = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Return only skills carrying this exact tag (case-insensitive).",
    )
    trust_tier = serializers.ChoiceField(
        choices=CommunitySkillTrustTier.choices,
        required=False,
        help_text="Filter to a single moderation tier.",
    )
    kind = serializers.ChoiceField(
        choices=CommunitySkillKind.choices,
        required=False,
        help_text="Filter to skills or to scouts. Omit to return both.",
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
        allow_blank=True,
        help_text="Name for the installed skill in your team. Defaults to the community skill's slug.",
    )
    variables = serializers.DictField(
        # trim_whitespace=False so a value's exact text (multiline snippets, leading/trailing
        # whitespace meant for the rendered output) survives into the installed skill.
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        required=False,
        help_text=(
            "Values for a template skill's declared variables, as a {name: value} map. Required only when "
            "installing a template (see the skill's `template_variables`); ignored for non-template skills."
        ),
    )


class CommunitySkillVoteResponseSerializer(serializers.Serializer):
    vote_count = serializers.IntegerField(help_text="Total upvotes after applying the toggle.")
    has_voted = serializers.BooleanField(help_text="Whether the requesting user is now an upvoter.")


class CommunitySkillRenderSerializer(serializers.Serializer):
    variables = serializers.DictField(
        # trim_whitespace=False so a value's exact text (multiline snippets, leading/trailing
        # whitespace meant for the rendered output) survives into the rendered body.
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        required=False,
        help_text=(
            "Values for a template skill's declared variables, as a {name: value} map. Required only when "
            "rendering a template (see the skill's `template_variables`); ignored for non-template skills."
        ),
    )


class CommunitySkillRenderResponseSerializer(serializers.Serializer):
    """A catalog entry with its template variables bound, for prefilling a create form. Nothing is
    persisted by rendering — the caller submits the result through the product's own create path."""

    slug = serializers.CharField(help_text="Slug of the rendered community skill.")
    kind = serializers.ChoiceField(
        choices=CommunitySkillKind.choices,
        help_text="Whether the rendered entry is a 'skill' or a 'scout'.",
    )
    name = serializers.CharField(help_text="Display name of the community skill.")
    description = serializers.CharField(help_text="What the skill does and when to use it.")
    body = serializers.CharField(help_text="The SKILL.md instruction content, with template variables bound.")
    scout_config = CommunitySkillScoutConfigSerializer(
        help_text="Schedule, emit posture and tags to prefill a scout with. Empty object for a skill."
    )
    variable_bindings = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="The {name: value} map the body was rendered with. Empty for a non-template skill.",
    )
