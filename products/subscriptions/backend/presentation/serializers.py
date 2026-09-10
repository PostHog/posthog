from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers


class PulseResearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=500,
        help_text="A public-web research query. It is searched once and only public results are considered.",
    )


class PulseResearchCitationSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable citation ID for this research call.")
    url = serializers.URLField(help_text="Validated public URL returned by the provider.")
    title = serializers.CharField(help_text="Bounded page title.")
    excerpt = serializers.CharField(help_text="Bounded extracted page evidence.")


class PulseResearchResponseSerializer(serializers.Serializer):
    citations = PulseResearchCitationSerializer(many=True, help_text="At most three bounded public citations.")
    degradation = serializers.ChoiceField(
        choices=["not_configured", "busy", "unavailable"],
        allow_null=True,
        required=False,
        help_text="Why public research was unavailable, when it could not run.",
    )


class ProactiveRepositoryOptionSerializer(serializers.Serializer):
    repository = serializers.CharField(
        read_only=True,
        help_text="Repository currently authorized for the requesting user, in owner/repository format.",
    )
    repository_integration_id = serializers.IntegerField(
        read_only=True,
        min_value=1,
        help_text="GitHub integration that currently authorizes this repository.",
    )


@extend_schema_serializer(many=False)
class ProactiveConfigurationOptionsSerializer(serializers.Serializer):
    proactive_available = serializers.BooleanField(
        read_only=True,
        help_text="Whether this PostHog instance is configured to generate proactive recommendations.",
    )
    public_web_research_available = serializers.BooleanField(
        read_only=True,
        help_text="Whether this PostHog instance is configured to use public web research for proactive recommendations.",
    )
    draft_pr_available = serializers.BooleanField(
        read_only=True,
        help_text="Whether this PostHog instance is configured to prepare draft pull requests for proactive recommendations.",
    )
    repositories = ProactiveRepositoryOptionSerializer(
        many=True,
        read_only=True,
        help_text="Repositories currently authorized for the requesting user to use for draft pull request preparation.",
    )
