"""DRF serializers for social_signals.

Wraps the facade's frozen-dataclass contracts in DataclassSerializer so the
schema flows through drf-spectacular into the generated TypeScript and MCP types.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    IngestResult,
    Mention,
    MentionAnalysis,
    MentionSource,
)


class MentionAnalysisSerializer(DataclassSerializer):
    class Meta:
        dataclass = MentionAnalysis


class MentionSerializer(DataclassSerializer):
    analyses = MentionAnalysisSerializer(
        many=True,
        required=False,
        help_text="Per-analyzer result rows attached to this mention.",
    )

    class Meta:
        dataclass = Mention


class MentionSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = MentionSource


class IngestResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = IngestResult


class CreateMentionSourceInputSerializer(serializers.Serializer):
    """POST body for creating a source for a given kind."""

    kind = serializers.CharField(help_text="Source kind enum value (e.g. 'octolens').")
