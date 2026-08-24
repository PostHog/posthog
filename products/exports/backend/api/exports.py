from datetime import timedelta
from typing import Any, Literal

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.timezone import now

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import EventSource, get_event_source, groups
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import Organization
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.security.url_validation import is_url_allowed
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs
from posthog.temporal.session_replay.rasterize_recording.types import (
    RASTERIZE_WORKFLOW_TIMEOUT,
    RasterizeRecordingInputs,
)

from products.exports.backend.models.exported_asset import (
    ExportedAsset,
    get_content_response,
    is_valid_session_recording_id,
)
from products.exports.backend.source_authentication import (
    get_export_source_authentication,
    required_scopes_for_export_target,
)
from products.exports.backend.stuck_exports import STUCK_EXPORT_MESSAGE, is_stuck_export
from products.product_analytics.backend.facade.models import Insight

# Full video exports per team per calendar month, tiered by plan.
FULL_VIDEO_EXPORTS_LIMIT_BY_TIER: dict[Literal["free", "paid", "enterprise"], int] = {
    "free": 10,
    "paid": 15,
    "enterprise": 25,
}


def get_full_video_exports_limit_for_organization(organization: Organization | None) -> int:
    """Monthly full video export limit for the organization's plan tier."""
    tier = organization.get_plan_tier() if organization is not None else "free"
    return FULL_VIDEO_EXPORTS_LIMIT_BY_TIER[tier]


logger = structlog.get_logger(__name__)


class ExportedAssetSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """Standard ExportedAsset serializer that doesn't return content."""

    export_format = serializers.ChoiceField(
        choices=ExportedAsset.get_supported_format_values(),
        read_only=True,
        help_text="File format of the generated export.",
    )
    has_content = serializers.BooleanField(read_only=True)
    filename = serializers.CharField(read_only=True)

    class Meta:
        model = ExportedAsset
        fields = [
            "id",
            "dashboard",
            "insight",
            "export_format",
            "created_at",
            "has_content",
            "export_context",
            "filename",
            "expires_after",
            "exception",
            "user_access_level",
        ]
        read_only_fields = ["id", "created_at", "has_content", "filename", "expires_after", "exception"]

    def to_representation(self, instance):
        """Override to show stuck exports as having an exception.

        Must stay free of side effects. A stuck export reads as stuck on every serialization of the
        row, so anything emitted here — an analytics event, a write — repeats for the life of the
        asset and on every poll of the list. Terminal state is recorded once, by whichever pipeline
        fails the export.
        """
        data = super().to_representation(instance)

        if is_stuck_export(instance):
            data["exception"] = STUCK_EXPORT_MESSAGE

        return data

    def validate(self, data: dict) -> dict:
        if not data.get("export_format"):
            raise ValidationError("Must provide export format")

        if not data.get("dashboard") and not data.get("insight") and not data.get("export_context"):
            raise ValidationError("Either dashboard, insight or export_context is required for an export.")

        if data.get("dashboard") and data["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if data.get("insight") and data["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        export_context = data.get("export_context") or {}
        if export_context.get("path") and (
            str(export_context.get("method", "GET")).upper() != "GET" or export_context.get("body") is not None
        ):
            raise ValidationError(
                {"export_context": ["Exports from API endpoints only support GET requests without a request body."]}
            )
        # Truthiness, not `is not None`: an absent or empty id is a no-op everywhere downstream,
        # and rejecting it here would 400 exports that never touch a recording.
        session_recording_id = export_context.get("session_recording_id")
        if session_recording_id and not is_valid_session_recording_id(session_recording_id):
            raise ValidationError({"export_context": ["Invalid session_recording_id."]})

        # Check full video export limit for team (video session recording exports)
        export_format = data.get("export_format")

        is_full_video_export = export_format in ExportedAsset.RASTERIZED_FORMATS and export_context.get(
            "session_recording_id"
        )

        if is_full_video_export:
            # Calculate the start of the current month
            current_time = now()
            start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            existing_full_video_exports_count = (
                ExportedAsset.objects.filter(
                    team_id=self.context["team_id"],
                    export_format__in=list(ExportedAsset.RASTERIZED_FORMATS),
                    export_context__session_recording_id__isnull=False,
                    created_at__gte=start_of_month,
                )
                .exclude(is_system=True)
                .count()
            )

            # Plan-tier default with an optional per-team override that acts as a floor.
            # Taking max() preserves the override's original purpose — bumping a team above
            # their tier default — without silently downgrading orgs whose tier default is
            # now higher than a legacy override set during the flat-10 era.
            get_organization = self.context.get("get_organization")
            organization = get_organization() if get_organization is not None else None
            team_limit = get_full_video_exports_limit_for_organization(organization)

            get_team = self.context.get("get_team")
            team = get_team() if get_team is not None else None
            if team is not None and team.extra_settings and "full_video_exports_limit" in team.extra_settings:
                limit_value = team.extra_settings["full_video_exports_limit"]
                try:
                    override_limit = int(limit_value)
                    if override_limit <= 0:
                        raise ValueError("Limit must be positive")
                    team_limit = max(team_limit, override_limit)
                except (ValueError, TypeError):
                    logger.warning(
                        "invalid_full_video_exports_limit",
                        team_id=team.id,
                        limit_value=limit_value,
                        limit_value_type=type(limit_value).__name__,
                    )

            if not self.context["request"].user.is_staff and existing_full_video_exports_count >= team_limit:
                raise ValidationError(
                    {
                        "export_limit_exceeded": [
                            f"Your team has reached the limit of {team_limit} full video exports this month."
                        ]
                    }
                )

        if export_context and export_context.get("heatmap_url"):
            ok, err = is_url_allowed(export_context["heatmap_url"])
            if not ok:
                raise ValidationError({"export_context": [f"heatmap_url not allowed: {err}"]})

        data["team_id"] = self.context["team_id"]
        return data

    def synthetic_create(self, reason: str, *args: Any, **kwargs: Any) -> ExportedAsset:
        # force_async here to avoid blocking patches to the /sharing endpoint
        return self._create_asset(self.validated_data, user=None, reason=reason, force_async=True)

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ExportedAsset:
        request = self.context["request"]
        source_authentication = get_export_source_authentication(request.successful_authenticator)
        if source_authentication is not None:
            validated_data.update(source_authentication)
        else:
            raise ValidationError(
                {"export_context": ["Exports from API endpoints do not support this authentication method."]}
            )
        self._assert_may_export_session_recording(validated_data)
        return self._create_asset(validated_data, user=request.user, reason=None)

    def _assert_may_export_session_recording(self, validated_data: dict) -> None:
        """Rendering a recording export must need the access that viewing the recording needs."""
        session_recording_id = (validated_data.get("export_context") or {}).get("session_recording_id")
        user_access_control = self.user_access_control
        if not session_recording_id or user_access_control is None:
            return

        from posthog.session_recordings.models.session_recording import SessionRecording

        recording = SessionRecording.objects.filter(
            team_id=validated_data["team_id"], session_id=session_recording_id
        ).first()
        if recording is not None:
            allowed = user_access_control.check_access_level_for_object(recording, required_level="viewer")
        else:
            allowed = user_access_control.check_access_level_for_resource("session_recording", required_level="viewer")

        if not allowed:
            raise PermissionDenied("You do not have access to this session recording.")

    def _create_asset(
        self,
        validated_data: dict,
        user: User | None,
        reason: str | None,
        force_async: bool = False,
    ) -> ExportedAsset:
        if user is not None:
            validated_data["created_by"] = user

        instance: ExportedAsset = super().create(validated_data)

        if instance.export_format not in ExportedAsset.SUPPORTED_FORMATS:
            raise serializers.ValidationError(
                {"export_format": [f"Export format {instance.export_format} is not supported."]}
            )

        team = instance.team

        posthoganalytics.capture(
            distinct_id=user.distinct_id if user else str(team.uuid),
            event="export requested",
            properties={
                **instance.get_analytics_metadata(),
                "force_async": force_async,
                "reason": reason,
            },
            groups=groups(team.organization, team),
        )

        if not force_async:
            if instance.is_rasterized_export:
                # recordings-only
                if not (instance.export_context and instance.export_context.get("session_recording_id")):
                    raise serializers.ValidationError(
                        {"export_format": ["Video export supports session recordings only."]}
                    )

                logger.info("starting_rasterize_recording_workflow", asset_id=instance.id)

                session_recording_id = instance.export_context.get("session_recording_id")

                async def _start():
                    client = await async_connect()
                    # Fire-and-forget: the render can take minutes, so don't block the request on it; the frontend polls.
                    await client.start_workflow(
                        "rasterize-recording",
                        RasterizeRecordingInputs(exported_asset_id=instance.id),
                        id=f"export-video-{instance.id}",
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                        execution_timeout=RASTERIZE_WORKFLOW_TIMEOUT,
                        search_attributes=TypedSearchAttributes(
                            search_attributes=[
                                SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.id),
                                SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=session_recording_id),
                            ]
                        ),
                    )

                try:
                    async_to_sync(_start)()
                    logger.info("rasterize_recording_workflow_dispatched", asset_id=instance.id)
                except Exception as e:
                    logger.exception("rasterize_recording_workflow_dispatch_failed", asset_id=instance.id, error=str(e))
                    raise
            else:
                self._start_export_workflow(instance, team, user, force_async=False)
        else:
            self._start_export_workflow(instance, team, user, force_async=True)

        posthoganalytics.capture(
            distinct_id=user.distinct_id if user else str(team.uuid),
            event="export created",
            properties={
                **instance.get_analytics_metadata(),
                "force_async": force_async,
                "reason": reason,
            },
            groups=groups(team.organization, team),
        )

        instance.refresh_from_db()
        insight_id = instance.insight_id
        dashboard_id = instance.dashboard_id
        if insight_id and not dashboard_id:  # logged against the insight's own activity history
            try:
                # nosemgrep: idor-lookup-without-team (insight_id validated as team-owned in validate())
                insight: Insight = Insight.objects.select_related("team__organization").get(id=insight_id)
                log_activity(
                    organization_id=insight.team.organization.id,
                    team_id=self.context["team_id"],
                    user=user,
                    was_impersonated=is_impersonated(self.context.get("request")),
                    item_id=insight_id,  # Type: ignore
                    scope="Insight",
                    activity="exported" if reason is None else f"exported for {reason}",
                    detail=Detail(
                        name=insight.name if insight.name else insight.derived_name,
                        short_id=insight.short_id,
                        changes=[
                            Change(
                                type="Insight",
                                action="exported",
                                field="export_format",
                                after=instance.export_format,
                            )
                        ],
                    ),
                )
            except Insight.DoesNotExist as ex:
                logger.warn(
                    "insight_exports.unknown_insight",
                    exception=ex,
                    insight_id=insight_id,
                )
                pass
        elif user is not None:
            # Dashboard, session recording, heatmap and SQL/HogQL query exports aren't tied to a
            # single insight's history, so they go under a dedicated ExportedAsset scope — making
            # every data export auditable. Insight-only exports are logged above (Insight scope) and
            # never reach here, so we never write two activity rows for one export. System/synthetic
            # exports (user is None, e.g. open-graph image renders) are intentionally not logged.
            self._log_exported_asset_activity(instance, user)
        return instance

    def _log_exported_asset_activity(self, instance: ExportedAsset, user: User) -> None:
        log_activity(
            organization_id=instance.team.organization_id,
            team_id=instance.team_id,
            user=user,
            was_impersonated=is_impersonated(self.context.get("request")),
            item_id=instance.id,
            scope="ExportedAsset",
            activity="exported",
            detail=Detail(
                name=self._describe_exported_asset(instance),
                type=instance.export_type,
                changes=[
                    Change(
                        type="ExportedAsset",
                        action="exported",
                        field="export_format",
                        after=instance.export_format,
                    )
                ],
            ),
        )

    @staticmethod
    def _describe_exported_asset(instance: ExportedAsset) -> str:
        """Human-readable name of what was exported, for the activity log entry."""
        context = instance.export_context or {}
        export_type = instance.export_type
        if export_type == "dashboard":
            return instance.dashboard.name if instance.dashboard and instance.dashboard.name else "a dashboard"
        if export_type == "insight":
            # Reachable only when an insight export is also tied to a dashboard (the insight-only
            # path is logged under the Insight scope above); name it after the insight either way.
            if instance.insight:
                return instance.insight.name or instance.insight.derived_name or "an insight"
            return "an insight"
        if export_type == "recording":
            session_recording_id = context.get("session_recording_id")
            return f"session recording {session_recording_id}" if session_recording_id else "a session recording"
        if export_type == "heatmap":
            heatmap_url = context.get("heatmap_url")
            return f"heatmap {heatmap_url}" if heatmap_url else "a heatmap"
        if context.get("source"):
            return "SQL query results"
        if context.get("filename"):
            return str(context["filename"])
        return "an export"

    def _start_export_workflow(
        self, instance: ExportedAsset, team: Team, user: User | None, force_async: bool = False
    ) -> None:
        request = self.context.get("request")
        source = get_event_source(request) if request else EventSource.EXPORT
        distinct_id = str(user.distinct_id) if user else str(team.id)

        workflow_inputs = ExportAssetWorkflowInputs(
            exported_asset_id=instance.id,
            team_id=team.id,
            distinct_id=distinct_id,
            slo=SloConfig(
                operation=SloOperation.EXPORT,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=team.id,
                resource_id=str(instance.id),
                distinct_id=distinct_id,
                start_properties={
                    "export_format": instance.export_format,
                    "export_type": instance.export_type,
                    "source": source,
                },
                completion_properties={
                    "export_format": instance.export_format,
                    "export_type": instance.export_type,
                    "source": source,
                },
            ),
        )

        async def _run():
            client = await async_connect()
            method = client.start_workflow if force_async else client.execute_workflow
            await method(
                ExportAssetWorkflow.run,
                workflow_inputs,
                id=f"export-asset-{instance.id}",
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
                execution_timeout=timedelta(minutes=35),
            )

        try:
            async_to_sync(_run)()
        except Exception as e:
            # Swallow workflow failures so the API always returns a 201 with the
            # ExportedAsset record. export_asset_direct populates the exception
            # field before re-raising, so callers (frontend toast, sharing
            # endpoint) can inspect the failure on the asset itself.
            logger.info(
                "export_workflow_failed_gracefully",
                asset_id=instance.id,
                error=str(e),
            )
            return

        logger.info(
            "export_workflow_dispatched" if force_async else "export_workflow_completed",
            asset_id=instance.id,
        )


class ExportedAssetCreateSerializer(ExportedAssetSerializer):
    export_format = serializers.ChoiceField(
        choices=[
            export_format
            for export_format in ExportedAsset.get_supported_format_values()
            if export_format != ExportedAsset.ExportFormat.JSONL
        ],
        help_text="File format to generate. Dataset JSONL exports use the dataset export endpoint.",
    )


@extend_schema(extensions={"x-product": "core"})
class ExportedAssetViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "export"
    # Both FKs are read on every retrieve to authorize the asset, so fetch them with it.
    queryset = ExportedAsset.objects.select_related("dashboard", "insight").order_by("-created_at")
    serializer_class = ExportedAssetSerializer

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        if self.action != "create":
            return None
        export_context = request.data.get("export_context") if isinstance(request.data, dict) else None
        return required_scopes_for_export_target(
            insight_id=request.data.get("insight") if isinstance(request.data, dict) else None,
            dashboard_id=request.data.get("dashboard") if isinstance(request.data, dict) else None,
            export_context=export_context if isinstance(export_context, dict) else None,
        )

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        return ExportedAssetCreateSerializer if self.action == "create" else ExportedAssetSerializer

    def safely_get_queryset(self, queryset):
        """List shows only exports created by the current user."""
        if self.action == "list":
            queryset = queryset.filter(created_by=self.request.user)

            session_recording_filter = self.request.query_params.get("session_recording_id")
            if session_recording_filter:
                queryset = queryset.filter(
                    export_context__session_recording_id=session_recording_filter,
                )

            context_path_filter = self.request.query_params.get("context_path")
            if context_path_filter:
                queryset = queryset.filter(export_context__path__icontains=context_path_filter)

            # Add export format filter
            export_format_filter = self.request.query_params.get("export_format")
            if export_format_filter and export_format_filter in ExportedAsset.get_supported_format_values():
                queryset = queryset.filter(export_format=export_format_filter)

        return queryset

    def safely_get_object(self, queryset):
        instance = get_object_or_404(queryset, pk=self.kwargs["pk"])
        export_context = instance.export_context or {}

        if instance.is_dataset_export and self.action != "content":
            raise NotFound()

        if not instance.is_session_recording_export and instance.created_by_id != self.request.user.id:
            raise NotFound()

        session_recording_id = export_context.get("session_recording_id")

        # Both can be set on one asset, and the renderer prefers the insight, so checking only the
        # first non-null one would let an accessible dashboard authorize an inaccessible insight.
        for related in (instance.dashboard, instance.insight):
            if related is not None and not self.user_access_control.check_access_level_for_object(
                related, required_level="viewer"
            ):
                raise NotFound()

        if not session_recording_id:
            return instance

        # Reached even when a dashboard or insight authorized above: an asset carrying both renders
        # the recording too, so a viewable dashboard must not stand in for access to it.
        from posthog.session_recordings.models.session_recording import SessionRecording

        recording = SessionRecording.objects.filter(team_id=instance.team_id, session_id=session_recording_id).first()
        if recording is not None:
            if not self.user_access_control.check_access_level_for_object(recording, required_level="viewer"):
                raise NotFound()
        elif instance.created_by_id != self.request.user.id:
            # No SessionRecording row — cannot run object-level RBAC; still enforce the team's
            # session_recording resource default for other users so detail/content are not fail-open.
            # The creator is exempt from this fallback only, because _assert_may_export_session_recording
            # ran the same check when they created the export, so retrieval must not be stricter than
            # creation — otherwise a session_recording default below viewer 404s the very user who just
            # took the screenshot, surfacing as an "Export complete!" toast followed by a blank error
            # page. Explicit object-level denies (the branch above) still apply to the creator once a
            # SessionRecording row exists.
            if not self.user_access_control.check_access_level_for_resource(
                "session_recording", required_level="viewer"
            ):
                raise NotFound()

        return instance

    # TODO: This should be removed as it is only used by frontend exporter and can instead use the api/sharing.py endpoint
    @action(methods=["GET"], detail=True, required_scopes=["export:read"])
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        if instance.is_dataset_export:
            dataset_id = (instance.export_context or {}).get("dataset_id")
            if not isinstance(dataset_id, str):
                raise NotFound()
            return HttpResponseRedirect(
                reverse(
                    "project_datasets-export-content",
                    kwargs={
                        "parent_lookup_team_id": instance.team_id,
                        "pk": dataset_id,
                        "export_id": instance.id,
                    },
                )
            )
        return get_content_response(
            instance,
            download=request.query_params.get("download") == "true",
            direct=request.query_params.get("direct") == "true",
        )
