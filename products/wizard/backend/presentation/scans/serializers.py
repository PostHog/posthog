from datetime import datetime, timedelta

from django.utils import timezone

from rest_framework import serializers

MAX_TOOLS_PER_SCAN = 300
MAX_SIGNALS_PER_TOOL = 50
# The wizard stamps `scanned_at` with the client clock. A day of slack covers clock skew, and anything
# later would let one scan claim to be newer than every scan that follows it.
MAX_SCANNED_AT_SKEW = timedelta(days=1)


class WizardScanSignalSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        max_length=32,
        help_text="Where the wizard found the tool, such as `npm`, `pypi`, `env_key` or `script_host`.",
    )
    name = serializers.CharField(
        max_length=255,
        help_text="The package name, `.env` key name or script host that matched. Never a `.env` value.",
    )
    file = serializers.CharField(
        max_length=512,
        required=False,
        allow_null=True,
        default=None,
        help_text="Path of the file the signal came from, relative to the scanned directory.",
    )


class WizardScanToolSerializer(serializers.Serializer):
    kind = serializers.CharField(
        max_length=64,
        help_text="The tool's kind in the wizard tool catalog, such as `Stripe` or `Amplitude`.",
    )
    signals = serializers.ListField(
        child=WizardScanSignalSerializer(),
        max_length=MAX_SIGNALS_PER_TOOL,
        help_text="The signals that matched this tool.",
    )


class RecordWizardScanRequestSerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=255, help_text="The wizard run that made the scan.")
    program = serializers.CharField(
        max_length=50,
        help_text="The wizard program that scanned, such as `posthog-integration` or `warehouse-source`.",
    )
    wizard_version = serializers.CharField(max_length=32, help_text="Version of the wizard that made the scan.")
    workspace_fingerprint = serializers.RegexField(
        r"^[0-9a-f]{64}$",
        max_length=64,
        help_text="sha256 hex digest that identifies the scanned repository without naming it.",
    )
    scanned_at = serializers.DateTimeField(help_text="When the wizard scanned the codebase.")
    tools = serializers.ListField(
        child=WizardScanToolSerializer(),
        max_length=MAX_TOOLS_PER_SCAN,
        help_text="Every tool the scan found. An empty list is a scan that found nothing.",
    )
    complete = serializers.BooleanField(
        default=True,
        help_text="False when the scan could not read the whole workspace. Tools it did not find are then kept.",
    )

    def validate_scanned_at(self, value: datetime) -> datetime:
        if value > timezone.now() + MAX_SCANNED_AT_SKEW:
            raise serializers.ValidationError("scanned_at is in the future.")
        return value


class WizardScanResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the stored scan.")
    created = serializers.BooleanField(
        help_text="False when this session had already reported its scan, so nothing changed."
    )
