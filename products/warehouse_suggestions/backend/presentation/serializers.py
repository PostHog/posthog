"""DRF serializers for warehouse_suggestions."""

from datetime import timedelta

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.data_modeling.backend.facade.api import MAX_LOOKBACK_SECONDS

from ..facade.contracts import (
    AcceptOptions,
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
    WarehouseSuggestionRefreshIntervalBasis,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)

MAX_REFRESH_INTERVAL_SECONDS = int(timedelta(days=30).total_seconds())


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
    refresh_mode = serializers.ChoiceField(
        choices=WarehouseSuggestionRefreshMode.choices,
        help_text="incremental: each refresh reads only rows with a new incremental_key value and updates rows by "
        "unique_key. full: each refresh rebuilds the whole table. Incremental is proposed only when the keys are "
        "certain from the query.",
    )
    refresh_interval_basis = serializers.ChoiceField(
        choices=WarehouseSuggestionRefreshIntervalBasis.choices,
        allow_null=True,
        help_text="Why the interval is not shorter. source_sync: the view's sources sync no faster. "
        "fastest_schedule: PostHog refreshes views no more often. read_rate: people read the view no more often. "
        "savings: a shorter interval would cost more than it saves. Null on suggestions made before this was "
        "recorded.",
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
            "incremental_key": {
                "help_text": "Output column whose advancing value marks new rows. A proposal only uses a date or "
                "datetime column the query groups by. "
                "Null for a full refresh."
            },
            "unique_key": {
                "help_text": "Output columns that identify a row, so a refresh updates rows instead of adding "
                "duplicates. Empty for a full refresh."
            },
            "lookback_seconds": {
                "help_text": "How far before the last refresh's highest incremental_key value each refresh reads "
                "again, in seconds. The last incremental_key value is always read again."
            },
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


@extend_schema_serializer(component_name="WarehouseSuggestionEvidence")
class SuggestionEvidenceSerializer(serializers.Serializer):
    days_with_data = serializers.IntegerField(
        required=False,
        help_text=(
            "Days of the 30-day usage window that PostHog has read history for. It counts days with reads in any "
            "project, so it shows how much history exists, not how active this project is."
        ),
    )
    human_requests = serializers.IntegerField(
        required=False, help_text="Queries people ran that read the subject in the usage window."
    )
    human_users = serializers.IntegerField(required=False, help_text="Distinct people who ran those queries.")
    human_days = serializers.IntegerField(required=False, help_text="Days on which people read the subject.")
    background_requests = serializers.IntegerField(
        required=False,
        help_text="Queries PostHog ran on its own that read the subject, such as cache warming and alerts.",
    )
    requests_by_surface = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Queries people ran per place they ran them, such as sql_editor, dashboard, insight or mcp.",
    )
    last_read_at = serializers.DateTimeField(
        required=False,
        help_text="When any query last read the subject, including queries PostHog ran on its own.",
    )


@extend_schema_serializer(component_name="WarehouseSuggestion")
class WarehouseSuggestionSerializer(DataclassSerializer):
    payload = SuggestionPayloadField(
        read_only=True, help_text="What accepting this suggestion would create or change. Shape depends on kind."
    )
    evidence = SuggestionEvidenceSerializer(
        help_text="The read counts that led to this suggestion. A field is missing when the subject had no reads."
    )
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
    subject_id = serializers.UUIDField(
        required=False, help_text="Only return suggestions about the view or table with this ID."
    )


class DismissWarehouseSuggestionSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=WarehouseSuggestionDismissalReason.choices, help_text="Why the suggestion is dismissed."
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, help_text="Optional note about the dismissal."
    )


@extend_schema_serializer(component_name="AcceptWarehouseSuggestion")
class AcceptWarehouseSuggestionSerializer(DataclassSerializer):
    class Meta:
        dataclass = AcceptOptions
        extra_kwargs = {
            "refresh_interval_seconds": {
                "allow_null": False,
                "min_value": 1,
                "max_value": MAX_REFRESH_INTERVAL_SECONDS,
                "help_text": "Materialize only: refresh interval to use instead of the proposed one, in seconds. "
                "Omit to keep the proposed interval.",
            },
            "refresh_mode": {
                "allow_null": False,
                "help_text": "Materialize only: incremental or full, instead of the proposed refresh_mode. Omit to "
                "keep the proposed one. Switching to incremental needs incremental_key and unique_key when the "
                "payload has none.",
            },
            "incremental_key": {
                "allow_null": False,
                "help_text": "Materialize only, incremental refresh only: an output column whose value only grows as "
                "rows arrive, such as a date, a datetime or an increasing number, instead of the proposed one. "
                "view-check-incremental lists the columns that qualify. Omit to keep the proposed key.",
            },
            "unique_key": {
                "allow_null": False,
                "allow_empty": False,
                "help_text": "Materialize only, incremental refresh only: output columns that identify a row, "
                "instead of the proposed ones. Must include every GROUP BY column. Omit to keep the proposed key.",
            },
            "lookback_seconds": {
                "allow_null": False,
                "min_value": 0,
                "max_value": MAX_LOOKBACK_SECONDS,
                "help_text": "Materialize only, incremental refresh only: how far before the last refresh's highest "
                "incremental_key value each refresh reads again, in seconds, so late rows are picked up. Omit to "
                "keep the proposed lookback.",
            },
        }
