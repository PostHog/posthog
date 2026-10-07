"""DRF serializers for warehouse_suggestions."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializeSuggestionPayload,
    Suggestion,
    SuggestionPayloadView,
    SuggestionReviewer,
    SuggestionStatus,
    VisibleSources,
)
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


@extend_schema_serializer(component_name="WarehouseSuggestionVisibleSources")
class VisibleSourcesSerializer(DataclassSerializer):
    class Meta:
        dataclass = VisibleSources
        extra_kwargs = {
            "names": {"help_text": "Names of the sources the caller may see."},
            "hidden_count": {"help_text": "How many more sources exist that the caller may not see."},
        }


@extend_schema_serializer(component_name="WarehouseSuggestionCertifyPayload")
class CertifyPayloadSerializer(DataclassSerializer):
    class Meta:
        dataclass = CertifyPayload
        extra_kwargs = {"subject_name": {"help_text": "Name of the view or table to certify."}}


@extend_schema_serializer(component_name="WarehouseSuggestionDeprecatePayload")
class DeprecatePayloadSerializer(DataclassSerializer):
    class Meta:
        dataclass = DeprecatePayload
        extra_kwargs = {
            "subject_name": {"help_text": "Name of the unread view to deprecate."},
            "refresh_seconds_per_month": {"help_text": "Time its refreshes take in a month, in seconds."},
            "refresh_bytes_per_month": {"help_text": "Bytes its refreshes read in a month."},
        }


@extend_schema_serializer(component_name="WarehouseSuggestionMaterializePayload")
class MaterializePayloadSerializer(DataclassSerializer):
    live_sources = VisibleSourcesSerializer(
        help_text="Sources that are always current, such as PostHog tables and direct connections."
    )
    unknown_sources = VisibleSourcesSerializer(
        help_text="Sources with no sync schedule, so their freshness is unknown."
    )

    class Meta:
        dataclass = MaterializeSuggestionPayload
        extra_kwargs = {
            "subject_name": {"help_text": "Name of the view to materialize."},
            "refresh_interval_seconds": {"help_text": "Proposed refresh interval, in seconds."},
            "saves_seconds_per_month": {"help_text": "Query time materializing saves in a month, in seconds."},
            "saves_bytes_per_month": {"help_text": "Bytes materializing saves from scanning in a month."},
            "freshness_today_seconds": {
                "help_text": "How old the view's data can be today, in seconds. Null when its sources are live."
            },
            "freshness_after_seconds": {"help_text": "How old the data can be once materialized, in seconds."},
        }


PAYLOAD_SERIALIZERS: dict[type, type[DataclassSerializer]] = {
    CertifyPayload: CertifyPayloadSerializer,
    DeprecatePayload: DeprecatePayloadSerializer,
    MaterializeSuggestionPayload: MaterializePayloadSerializer,
}


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="WarehouseSuggestionPayload",
        serializers=list(PAYLOAD_SERIALIZERS.values()),
        resource_type_field_name=None,
    )
)
class SuggestionPayloadField(serializers.Field):
    def to_representation(self, value: SuggestionPayloadView) -> dict:
        return PAYLOAD_SERIALIZERS[type(value)](value).data


@extend_schema_serializer(component_name="WarehouseSuggestionStatus")
class WarehouseSuggestionStatusSerializer(DataclassSerializer):
    class Meta:
        dataclass = SuggestionStatus
        extra_kwargs = {
            "enabled": {"help_text": "False when the project turned suggestions off."},
            "eligible": {"help_text": "Whether the project reads its views often enough to get suggestions."},
            "days_with_data": {"help_text": "Days of read history the last run had, up to the window."},
            "window_days": {"help_text": "Days of read history a full window holds."},
            "paused_reason": {"help_text": "Why new suggestions stopped showing. Null while they show."},
            "refreshed_at": {"help_text": "When the daily job last ran for this project."},
        }


@extend_schema_serializer(component_name="WarehouseSuggestion")
class WarehouseSuggestionSerializer(DataclassSerializer):
    payload = SuggestionPayloadField(
        read_only=True, help_text="What accepting this suggestion would create or change. Shape depends on kind."
    )
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
