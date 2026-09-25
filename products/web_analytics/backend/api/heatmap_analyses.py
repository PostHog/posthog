from datetime import datetime, timedelta
from typing import cast

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.models import User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.exports.backend.models.exported_asset import ExportedAsset, read_content
from products.web_analytics.backend.api.heatmaps_api import (
    HeatmapsRequestSerializer,
    _heatmaps_cohort_filter_enabled,
    _heatmaps_event_filter_enabled,
)
from products.web_analytics.backend.api.heatmaps_utils import heatmaps_flag_enabled
from products.web_analytics.backend.heatmap_analysis import (
    PageVariant,
    RecordingAnalysis,
    VariantMember,
    group_page_states,
)
from products.web_analytics.backend.models import SavedHeatmap
from products.web_analytics.backend.models.heatmap_analysis import HeatmapAnalysis, HeatmapAnalysisRecording
from products.web_analytics.backend.tasks.heatmap_analysis import analyze_heatmap

ANALYSIS_IN_PROGRESS = "Another historical heatmap is being analyzed. Try again when it finishes."
MAX_ANALYSIS_RANGE = timedelta(days=90, hours=1)


class HeatmapAnalysisCreateSerializer(serializers.Serializer):
    heatmap_id = serializers.UUIDField(help_text="Saved heatmap to analyze.")
    date_from = serializers.DateTimeField(help_text="Inclusive start of the historical range, with timezone.")
    date_to = serializers.DateTimeField(help_text="Exclusive end of the historical range, with timezone.")
    viewport_width = serializers.IntegerField(
        min_value=200, max_value=4000, help_text="Recorded viewport width in CSS pixels."
    )
    filter_test_accounts = serializers.BooleanField(
        default=False, help_text="Exclude the project's internal and test traffic."
    )
    cohort_ids = serializers.CharField(
        default="[]", help_text="JSON array of cohort IDs, using existing heatmap cohort filter semantics."
    )
    events = serializers.CharField(default="[]", help_text="JSON array of heatmap event filters.")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        date_from, date_to = cast(datetime, attrs["date_from"]), cast(datetime, attrs["date_to"])
        if date_to <= date_from or date_to - date_from > MAX_ANALYSIS_RANGE:
            raise serializers.ValidationError("Choose a date range between one second and 90 days.")
        if date_from > timezone.now():
            raise serializers.ValidationError("Choose dates in the past.")
        attrs["date_to"] = min(date_to, timezone.now())
        filters = HeatmapsRequestSerializer(
            data={"cohort_ids": attrs.pop("cohort_ids"), "events": attrs.pop("events")}, context=self.context
        )
        filters.is_valid(raise_exception=True)
        attrs["filters"] = {
            "cohort_ids": filters.validated_data.get("cohort_ids", []),
            "events": filters.validated_data.get("events", []),
            "filter_test_accounts": attrs.pop("filter_test_accounts"),
        }
        return attrs


class HeatmapAnalysisClickSerializer(serializers.Serializer):
    x = serializers.FloatField(help_text="Document x coordinate in CSS pixels.")
    y = serializers.FloatField(help_text="Document y coordinate in CSS pixels.")
    count = serializers.IntegerField(help_text="Number of attributable recorded clicks.")


class HeatmapAnalysisAlternativeSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Opaque representative moment identifier.")
    session_id = serializers.CharField(help_text="Source recording ID.")
    timestamp = serializers.FloatField(help_text="Absolute recorded timestamp in milliseconds.")


class HeatmapAnalysisVariantSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Page variant identifier for this algorithm version.")
    session_id = serializers.CharField(help_text="Recording used for the background.")
    window_id = serializers.IntegerField(help_text="Recording window containing the background.")
    timestamp = serializers.FloatField(help_text="Background timestamp in milliseconds since the epoch.")
    representative_replaced = serializers.BooleanField(
        help_text="Whether an unavailable saved background was replaced with another available moment."
    )
    width = serializers.IntegerField(help_text="Recorded page width in CSS pixels.")
    height = serializers.IntegerField(help_text="Reconstructed page height in CSS pixels.")
    recordings = serializers.IntegerField(help_text="Distinct analyzed recordings containing this variant.")
    visits = serializers.IntegerField(help_text="Distinct analyzed page visits containing this variant.")
    first_seen = serializers.FloatField(help_text="Earliest analyzed occurrence in milliseconds.")
    last_seen = serializers.FloatField(help_text="Latest analyzed occurrence in milliseconds.")
    clicks = HeatmapAnalysisClickSerializer(many=True, help_text="Clicks aligned to this background.")
    alternatives = HeatmapAnalysisAlternativeSerializer(many=True, help_text="Alternative background moments.")


class HeatmapAnalysisFiltersSerializer(serializers.Serializer):
    cohort_ids = serializers.ListField(
        child=serializers.IntegerField(), default=list, help_text="Cohorts used for this saved analysis."
    )
    events = serializers.ListField(
        child=serializers.DictField(), default=list, help_text="Event filters used for this saved analysis."
    )
    filter_test_accounts = serializers.BooleanField(
        default=False, help_text="Whether internal and test traffic was excluded."
    )


class HeatmapAnalysisSerializer(serializers.ModelSerializer):
    filters = HeatmapAnalysisFiltersSerializer(
        read_only=True, help_text="Filters frozen when the analysis was created."
    )

    class Meta:
        model = HeatmapAnalysis
        fields = [
            "id",
            "heatmap_id",
            "url",
            "date_from",
            "date_to",
            "viewport_width",
            "status",
            "sampled_recordings",
            "excluded_recordings",
            "error",
            "created_at",
            "filters",
        ]
        read_only_fields = fields
        extra_kwargs = {
            name: {"help_text": description}
            for name, description in {
                "url": "Exact page URL analyzed.",
                "date_from": "Inclusive range start.",
                "date_to": "Exclusive range end.",
                "viewport_width": "Requested viewport width in CSS pixels.",
                "status": "Analysis processing state.",
                "sampled_recordings": "Number of recordings selected for analysis.",
                "excluded_recordings": "Recordings that could not be analyzed.",
                "error": "User-facing failure reason, if any.",
                "created_at": "When the analysis was requested.",
            }.items()
        }


class HeatmapAnalysisResultSerializer(serializers.Serializer):
    analysis = HeatmapAnalysisSerializer(help_text="Saved historical analysis.")
    variants = HeatmapAnalysisVariantSerializer(
        many=True, help_text="Variants from currently available source recordings."
    )
    analyzed_visits = serializers.IntegerField(help_text="Distinct successfully reconstructed visits across variants.")
    unavailable_recordings = serializers.IntegerField(
        help_text="Analyzed recordings no longer available to this viewer."
    )
    excluded_clicks = serializers.IntegerField(help_text="Recorded clicks that could not be aligned.")


class HeatmapAnalysisRepresentativeSerializer(serializers.Serializer):
    variant_id = serializers.CharField(max_length=24, help_text="Variant whose background should change.")
    moment_id = serializers.CharField(max_length=260, help_text="One of the variant's alternative moment IDs.")


class HeatmapAnalysisViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "heatmap"
    scope_object_read_actions = ["retrieve", "background"]
    serializer_class = HeatmapAnalysisSerializer
    queryset = HeatmapAnalysis.objects.unscoped().none()

    def safely_get_queryset(self, queryset: QuerySet[HeatmapAnalysis]) -> QuerySet[HeatmapAnalysis]:
        return (
            HeatmapAnalysis.objects.for_team(self.team_id)
            .select_related("team__organization", "heatmap", "created_by")
            .filter(heatmap__deleted=False)
        )

    def safely_get_object(self, queryset: QuerySet[HeatmapAnalysis]) -> HeatmapAnalysis:
        analysis: HeatmapAnalysis = get_object_or_404(queryset, id=self.kwargs["pk"])
        if not self.user_access_control.check_access_level_for_object(
            analysis.heatmap, "viewer" if self.request.method == "GET" else "editor"
        ):
            raise exceptions.PermissionDenied()
        return analysis

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise exceptions.PermissionDenied("Historical heatmaps require a signed-in user.")
        if not self.team.session_recording_opt_in or not heatmaps_flag_enabled(
            "heatmaps-historical-variants",
            cast(User, request.user).distinct_id or "",
            team_id=self.team_id,
            organization_id=str(self.team.organization_id),
        ):
            raise exceptions.NotFound()
        if not self.user_access_control.check_access_level_for_resource(
            "heatmap", "viewer"
        ) or not self.user_access_control.check_access_level_for_resource("session_recording", "viewer"):
            raise exceptions.PermissionDenied("Project-wide heatmap and Session replay access are required.")

    def _recordings(self, analysis: HeatmapAnalysis, session_id: str | None = None) -> dict[str, RecordingAnalysis]:
        queryset = HeatmapAnalysisRecording.objects.for_team(self.team_id).filter(
            analysis=analysis,
            asset__expires_after__gt=timezone.now(),
        )
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        sources = list(queryset.select_related("asset"))
        available = SessionReplayEvents().batch_exists([source.session_id for source in sources], self.team)
        stored = {
            recording.session_id: recording
            for recording in SessionRecording.objects.filter(team_id=self.team_id, session_id__in=available)
        }
        result: dict[str, RecordingAnalysis] = {}
        for source in sources:
            recording = stored.get(source.session_id) or SessionRecording(team=self.team, session_id=source.session_id)
            if (
                not available.get(source.session_id)
                or recording.deleted
                or not self.user_access_control.check_access_level_for_object(recording, "viewer")
            ):
                continue
            raw = read_content(source.asset)
            if raw:
                result[source.session_id] = RecordingAnalysis.model_validate_json(raw)
        return result

    def _representative(self, analysis: HeatmapAnalysis, variant_id: str) -> VariantMember | None:
        selected = analysis.representatives.get(variant_id)
        if selected:
            session_id = selected.rsplit(":", 2)[0]
            recording = self._recordings(analysis, session_id).get(session_id)
            for state in recording.states if recording else []:
                member = VariantMember(session_id=session_id, state=state)
                if (
                    state.variant_id == variant_id
                    and state.signature
                    and state.image
                    and PageVariant.member_id(member) == selected
                ):
                    return member
        variant = next(
            (variant for variant in group_page_states(self._recordings(analysis)) if variant.id == variant_id), None
        )
        return variant.representative(selected) if variant else None

    def _result(
        self,
        analysis: HeatmapAnalysis,
        recordings: dict[str, RecordingAnalysis] | None = None,
        variants: list[PageVariant] | None = None,
    ) -> dict[str, object]:
        if (
            analysis.is_active
            and analysis.updated_at < timezone.now() - HeatmapAnalysis.STALE_AFTER
            and HeatmapAnalysis.expire_stale(self.team_id)
        ):
            analysis.refresh_from_db()
        if recordings is None:
            recordings = {} if analysis.is_active else self._recordings(analysis)
        if variants is None:
            variants = group_page_states(recordings)
        representatives = [variant.representative(analysis.representatives.get(variant.id)) for variant in variants]
        serialized = HeatmapAnalysisSerializer(analysis).data
        if (
            not recordings
            and analysis.status in ["completed", "partial"]
            and analysis.sampled_recordings > analysis.excluded_recordings
        ):
            serialized["status"] = "unavailable"
        return {
            "analysis": serialized,
            "variants": [
                variant.summary(analysis.representatives.get(variant.id), representative)
                for variant, representative in zip(variants, representatives)
            ],
            "analyzed_visits": len(set().union(*(variant.visit_keys() for variant in variants))),
            "unavailable_recordings": max(
                0, analysis.sampled_recordings - analysis.excluded_recordings - len(recordings)
            ),
            "excluded_clicks": sum(recording.excluded_clicks for recording in recordings.values())
            + sum(
                variant.excluded_clicks(representative) for variant, representative in zip(variants, representatives)
            ),
        }

    @extend_schema(request=HeatmapAnalysisCreateSerializer, responses={202: HeatmapAnalysisSerializer})
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = HeatmapAnalysisCreateSerializer(data=request.data, context={"team": self.team})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        filters = data["filters"]
        if filters["cohort_ids"] and not _heatmaps_cohort_filter_enabled(cast(User, request.user), self.team):
            raise exceptions.PermissionDenied("Cohort filters are not enabled for this project.")
        if filters["events"] and not _heatmaps_event_filter_enabled(cast(User, request.user), self.team):
            raise exceptions.PermissionDenied("Event filters are not enabled for this project.")
        heatmap = SavedHeatmap.objects.filter(team_id=self.team_id, id=data["heatmap_id"], deleted=False).first()
        if heatmap is None:
            raise exceptions.NotFound()
        url = heatmap.data_url or heatmap.url
        if "*" in url:
            raise exceptions.ValidationError("Choose a heatmap for one exact URL.")
        if not self.user_access_control.check_access_level_for_object(heatmap, "editor"):
            raise exceptions.PermissionDenied()
        HeatmapAnalysis.expire_stale(self.team_id)
        active = self.get_queryset().filter(status__in=HeatmapAnalysis.ACTIVE_STATUSES).first()
        if active:
            if (
                active.heatmap_id == heatmap.id
                and active.date_from == data["date_from"]
                and active.date_to == data["date_to"]
                and active.viewport_width == data["viewport_width"]
                and active.filters == filters
            ):
                return Response(HeatmapAnalysisSerializer(active).data, status=status.HTTP_202_ACCEPTED)
            raise exceptions.Throttled(detail=ANALYSIS_IN_PROGRESS)
        try:
            with transaction.atomic():
                analysis = HeatmapAnalysis.objects.for_team(self.team_id).create(
                    team=self.team,
                    created_by=cast(User, request.user),
                    heatmap=heatmap,
                    url=url,
                    date_from=data["date_from"],
                    date_to=data["date_to"],
                    viewport_width=data["viewport_width"],
                    filters=filters,
                )
                transaction.on_commit(lambda: analyze_heatmap.delay(self.team_id, str(analysis.id)))
        except IntegrityError:
            raise exceptions.Throttled(detail=ANALYSIS_IN_PROGRESS)
        return Response(HeatmapAnalysisSerializer(analysis).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses=HeatmapAnalysisResultSerializer)
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(self._result(self.get_object()), headers={"Cache-Control": "no-store"})

    @extend_schema(request=HeatmapAnalysisRepresentativeSerializer, responses=HeatmapAnalysisResultSerializer)
    @action(methods=["POST"], detail=True)
    def representative(self, request: Request, **kwargs: object) -> Response:
        analysis = self.get_object()
        serializer = HeatmapAnalysisRepresentativeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recordings = self._recordings(analysis)
        variants = group_page_states(recordings)
        variant = next((variant for variant in variants if variant.id == data["variant_id"]), None)
        if variant is None or not any(PageVariant.member_id(member) == data["moment_id"] for member in variant.members):
            raise exceptions.ValidationError("Choose an available moment from this variant.")
        with transaction.atomic():
            locked = self.get_queryset().select_for_update(of=("self",)).get(id=analysis.id)
            locked.representatives = {**locked.representatives, data["variant_id"]: data["moment_id"]}
            locked.save(update_fields=["representatives", "updated_at"])
        return Response(self._result(locked, recordings, variants), headers={"Cache-Control": "no-store"})

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    @action(methods=["GET"], detail=True, url_path="background/(?P<variant_id>[a-f0-9]{24})")
    def background(self, request: Request, variant_id: str, **kwargs: object) -> HttpResponse:
        analysis = self.get_object()
        representative = self._representative(analysis, variant_id)
        if representative is None:
            raise exceptions.NotFound("This background is no longer available. Refresh the analysis.")
        asset = ExportedAsset.objects.filter(
            team_id=self.team_id,
            id=representative.state.image,
            export_context__session_recording_id=representative.session_id,
        ).first()
        image = read_content(asset) if asset else None
        if image is None:
            raise exceptions.NotFound()
        return HttpResponse(image, content_type="image/png", headers={"Cache-Control": "no-store"})
