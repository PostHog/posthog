"""DRF serializers for warehouse_suggestions."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import Suggestion, SuggestionReviewer
from ..facade.enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)


@extend_schema_field(OpenApiTypes.OBJECT)
class JsonObjectField(serializers.JSONField):
    pass


@extend_schema_serializer(component_name="WarehouseSuggestionReviewer")
class WarehouseSuggestionReviewerSerializer(DataclassSerializer):
    class Meta:
        dataclass = SuggestionReviewer
        extra_kwargs = {
            "id": {"help_text": "User id."},
            "first_name": {"help_text": "User first name."},
            "email": {"help_text": "User email."},
        }


@extend_schema_serializer(component_name="WarehouseSuggestion")
class WarehouseSuggestionSerializer(DataclassSerializer):
    payload = JsonObjectField(help_text="What accepting this suggestion would create or change. Shape depends on kind.")
    evidence = JsonObjectField(help_text="The usage numbers that led to this suggestion.")
    created_asset = JsonObjectField(
        allow_null=True, help_text="What accepting this suggestion created. Null until accepted."
    )
    reviewed_by = WarehouseSuggestionReviewerSerializer(
        allow_null=True, help_text="Who accepted or dismissed this suggestion. Null while it is open."
    )
    kind = serializers.ChoiceField(
        choices=WarehouseSuggestionKind.choices,
        help_text="What the suggestion proposes: certify, deprecate or materialize the subject.",
    )
    subject_kind = serializers.ChoiceField(
        choices=WarehouseSuggestionSubjectKind.choices,
        help_text="Whether the subject is a saved query (view) or a warehouse table.",
    )
    status = serializers.ChoiceField(
        choices=WarehouseSuggestionStatus.choices,
        help_text="proposed until someone accepts or dismisses it, or the job expires it.",
    )
    dismissal_reason = serializers.ChoiceField(
        choices=WarehouseSuggestionDismissalReason.choices,
        allow_null=True,
        help_text="Why the suggestion was dismissed.",
    )
    asset_outcome = serializers.ChoiceField(
        choices=WarehouseSuggestionAssetOutcome.choices,
        allow_null=True,
        help_text="What happened to the asset an accepted suggestion created.",
    )

    class Meta:
        dataclass = Suggestion
        extra_kwargs = {
            "id": {"help_text": "Suggestion identifier."},
            "subject_id": {"help_text": "Id of the view or table the suggestion is about."},
            "payload_version": {"help_text": "Version of the payload shape for this kind."},
            "evidence_window_start": {"help_text": "Start of the usage window the evidence covers."},
            "evidence_window_end": {"help_text": "End of the usage window the evidence covers."},
            "last_seen_at": {"help_text": "When the daily job last found evidence for this suggestion."},
            "score": {"help_text": "How strongly the evidence supports the suggestion. Higher comes first."},
            "surfaced_at": {"help_text": "When the suggestion was first shown. Null while it waits for a slot."},
            "reviewed_at": {"help_text": "When the suggestion was accepted or dismissed."},
            "dismissal_note": {"help_text": "Free-text note left when dismissing."},
            "can_act": {
                "help_text": "Whether the caller has edit access to the subject and so may accept, dismiss or resume."
            },
        }


class WarehouseSuggestionListQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=WarehouseSuggestionKind.choices, required=False, help_text="Only return suggestions of this kind."
    )
    status = serializers.ChoiceField(
        choices=WarehouseSuggestionStatus.choices, required=False, help_text="Only return suggestions in this status."
    )


class DismissWarehouseSuggestionSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=WarehouseSuggestionDismissalReason.choices, help_text="Why the suggestion is dismissed."
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, help_text="Optional note about the dismissal."
    )
