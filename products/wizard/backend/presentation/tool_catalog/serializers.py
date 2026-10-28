from django.db.models import TextChoices

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers


class WizardSetupMode(TextChoices):
    IN_CLI = "in-cli", "In the terminal"
    DEEP_LINK = "deep-link", "In the app"


class WizardCatalogToolSignalsSerializer(serializers.Serializer):
    env_key_patterns = serializers.ListField(
        child=serializers.CharField(),
        help_text="Anchored regexes matched against `.env` key names. Values are never read.",
    )
    script_hosts = serializers.ListField(
        child=serializers.CharField(),
        help_text="Hosts matched against script URLs. A host also matches its subdomains.",
    )
    packages = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Package names keyed by ecosystem, such as `npm`, `pypi` or `maven`.",
    )


class WizardCatalogToolSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="Unique tool identifier, such as `Stripe` or `Hotjar`.")
    label = serializers.CharField(help_text="Human-readable tool name.")  # type: ignore[assignment]
    warehouse_source_type = serializers.CharField(
        allow_null=True,
        help_text="Data warehouse source type the tool imports as, or null for a tool with no warehouse source.",
    )
    wizard_setup_mode = serializers.ChoiceField(
        choices=WizardSetupMode.choices,
        allow_null=True,
        help_text="How the wizard sets up the source: in the terminal or in the app. Null for a tool with no warehouse source.",
    )
    alternative_to = serializers.ListField(
        child=serializers.CharField(), help_text="PostHog products this tool is an alternative to."
    )
    superseded_by = serializers.ListField(
        child=serializers.CharField(),
        help_text="Kinds that reach the same data through a more specific source. When one of them also matches, the wizard drops this tool.",
    )
    signals = WizardCatalogToolSignalsSerializer(help_text="How the wizard detects the tool in a codebase.")


# The catalog is served from `list`, which drf-spectacular documents as an array by default.
@extend_schema_serializer(many=False)
class WizardToolCatalogSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(
        help_text="Bumped when the shape changes in a way an older wizard cannot read."
    )
    tools = WizardCatalogToolSerializer(many=True, help_text="Every tool the wizard can detect.")
