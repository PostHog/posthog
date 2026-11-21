import json
from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from pydantic import (
    JsonValue,
    ValidationError as PydanticValidationError,
)
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import InvestigationDocument, InvestigationSummary, SavedInvestigation
from ..facade.enums import InvestigationStage


@extend_schema_field(InvestigationDocument)  # type: ignore[arg-type]  # Supported by drf-spectacular's Pydantic extension.
class InvestigationDocumentField(serializers.Field):
    def to_internal_value(self, data: Any) -> InvestigationDocument:
        data = serializers.JSONField().to_internal_value(data)
        if len(json.dumps(data)) > 500_000:
            raise serializers.ValidationError(
                "This investigation is too large. Remove older runs or shorten evidence notes."
            )
        try:
            return InvestigationDocument.model_validate(data)
        except PydanticValidationError as exc:
            raise serializers.ValidationError("Invalid investigation document. Check its fields and limits.") from exc

    def to_representation(self, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return value


class InvestigationSummarySerializer(DataclassSerializer):
    status = serializers.ChoiceField(choices=InvestigationStage.choices, help_text="Current investigation stage.")

    class Meta:
        dataclass = InvestigationSummary
        extra_kwargs = {
            "id": {"help_text": "Stable identifier for this investigation."},
            "question": {"help_text": "The question this investigation answers."},
            "revision": {"help_text": "Current revision to pass with the next update."},
            "evidence_count": {"help_text": "Number of evidence queries and links."},
            "run_count": {"help_text": "Number of retained result snapshots."},
            "updated_at": {"help_text": "When the investigation was last saved."},
            "created_at": {"help_text": "When the investigation was created."},
            "created_by": {"help_text": "ID of the creator, or null if the account was deleted."},
        }


class InvestigationSerializer(InvestigationSummarySerializer):
    status = serializers.ChoiceField(choices=InvestigationStage.choices, help_text="Current investigation stage.")
    document = InvestigationDocumentField(
        help_text="Question, evidence, hypotheses, decisions, and bounded result snapshots."
    )

    class Meta:
        dataclass = SavedInvestigation
        extra_kwargs = InvestigationSummarySerializer.Meta.extra_kwargs


class InvestigationCreateSerializer(serializers.Serializer):
    document = InvestigationDocumentField(help_text="The investigation document to save. Version must be 1.")


class InvestigationUpdateSerializer(serializers.Serializer):
    revision = serializers.IntegerField(
        min_value=1, help_text="Last read revision. Stale writes are rejected with HTTP 409."
    )
    document = InvestigationDocumentField(
        required=False, help_text="Replacement document, preserving existing evidence and run IDs."
    )
    deleted = serializers.BooleanField(
        default=False, help_text="Archive this investigation and remove it from the list."
    )


class InvestigationListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, default="", max_length=500, help_text="Search the investigation question."
    )
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Number of investigations to skip.")
    limit = serializers.IntegerField(
        default=30, min_value=1, max_value=100, help_text="Maximum number of investigations to return."
    )


@extend_schema_serializer(many=False)
class InvestigationListSerializer(serializers.Serializer):
    results = InvestigationSummarySerializer(
        many=True, help_text="Investigations ordered by most recently updated first."
    )
    count = serializers.IntegerField(help_text="Total number of matching investigations.")


class InvestigationErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What prevented the operation and how to recover.")
