"""
TEMPORARY: This file is in transition.

Current state: Moved from ee/clickhouse/views/experiments.py to products/experiments/backend/presentation/
to break down the monolith incrementally. Serializers split into serializers.py (PR #2) but this file
still directly imports from service/models layers (violating product architecture temporarily).

This will be refactored incrementally in subsequent PRs to match the product architecture pattern.
"""

import asyncio
from typing import Any, Literal, cast

from django.conf import settings
from django.db.models import Prefetch, QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.approvals.mixins import ApprovalHandlingMixin
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.evaluation_context import FeatureFlagEvaluationContext
from posthog.models.filters.filter import Filter
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.temporal.common.client import sync_connect
from posthog.temporal.experiments.models import ExperimentTimeseriesRecalculationWorkflowInputs
from posthog.user_permissions import UserPermissions

# TODO: Route through facade instead of direct import
from products.experiments.backend.experiment_service import ExperimentService

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentTimeseriesRecalculation,
    experiment_has_legacy_metrics,
)
from products.experiments.backend.presentation.serializers import (
    CopyExperimentToProjectSerializer,
    EndExperimentSerializer,
    ExperimentSerializer,
    ShipVariantSerializer,
)
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

from ee.clickhouse.queries.experiments.utils import requires_flag_warning


@extend_schema_view(
    # PATCH /experiments/{id}/
    # DRF mixin calls implementation at ExperimentSerializer.update
    partial_update=extend_schema(
        description="Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.",
    ),
    # POST /experiments/ — DRF mixin calls ExperimentSerializer.create
    create=extend_schema(
        description="Create a new experiment in draft status with optional metrics.",
    ),
    # GET /experiments/{id}/ — DRF mixin, read-only serialization via ExperimentSerializer
    retrieve=extend_schema(
        description="Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.",
    ),
    # GET /experiments/ — DRF mixin, filtering via ExperimentService.filter_experiments_queryset
    list=extend_schema(
        description="List experiments for the current project. Supports filtering by status and archival state.",
        parameters=[
            OpenApiParameter(
                name="status",
                location=OpenApiParameter.QUERY,
                type=str,
                enum=["draft", "running", "paused", "stopped", "complete", "all"],
                description=(
                    'Filter by experiment status. "running" and "paused" are mutually exclusive: "running" returns '
                    'launched experiments with an active feature flag, "paused" returns launched experiments whose '
                    'feature flag is deactivated. "complete" is an alias for "stopped". "all" disables status '
                    "filtering."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="archived",
                location=OpenApiParameter.QUERY,
                type=bool,
                description="Filter by archived state. Defaults to non-archived experiments only.",
                required=False,
            ),
            OpenApiParameter(
                name="feature_flag_id",
                location=OpenApiParameter.QUERY,
                type=int,
                description="Filter to experiments linked to the given feature flag ID.",
                required=False,
            ),
            OpenApiParameter(
                name="created_by_id",
                location=OpenApiParameter.QUERY,
                type=int,
                description="Filter to experiments created by the given user ID.",
                required=False,
            ),
            OpenApiParameter(
                name="search",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Free-text search applied to the experiment name (case-insensitive).",
                required=False,
            ),
            OpenApiParameter(
                name="order",
                location=OpenApiParameter.QUERY,
                type=str,
                description=(
                    "Field to order by. Prefix with '-' for descending. Allowlisted fields include name, "
                    "created_at, updated_at, start_date, end_date, duration, and status."
                ),
                required=False,
            ),
        ],
    ),
    # DELETE /experiments/{id}/
    # Logic and API docs defined in posthog/api/forbid_destroy_model.py (hard delete not allowed)
)
@extend_schema(tags=["experiments"])
class EnterpriseExperimentsViewSet(
    # ApprovalHandlingMixin converts ApprovalRequired exceptions (raised by
    # FeatureFlagSerializer in ship_variant) into 409 HTTP responses. The
    # approval check itself lives in the service layer — this mixin is only
    # responsible for exception-to-response formatting.
    ApprovalHandlingMixin,
    ForbidDestroyModel,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object: Literal["experiment"] = "experiment"
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.prefetch_related(
        Prefetch(
            "feature_flag__flag_evaluation_contexts",
            queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
        ),
        "feature_flag",
        "created_by",
        "holdout",
        "experimenttosavedmetric_set",
        "saved_metrics",
    ).all()
    ordering = "-created_at"

    def safely_get_queryset(self, queryset) -> QuerySet:
        request = getattr(self, "request", None)
        service = ExperimentService(team=self.team, user=getattr(request, "user", None))
        return service.filter_experiments_queryset(
            queryset,
            action=self.action,
            query_params=getattr(request, "query_params", None),
            request_data=getattr(request, "data", None),
        )

    # ******************************************
    # /projects/:id/experiments/requires_flag_implementation
    #
    # Returns current results of an experiment, and graphs
    # 1. Probability of success
    # 2. Funnel breakdown graph to display
    # ******************************************
    @action(methods=["GET"], detail=False, required_scopes=["experiment:read"])
    def requires_flag_implementation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filter = Filter(request=request, team=self.team).shallow_clone({"date_from": "-7d", "date_to": ""})

        warning = requires_flag_warning(filter, self.team)

        return Response({"result": warning})

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def launch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Launch a draft experiment.

        Validates the experiment is in draft state, activates its linked feature flag,
        sets start_date to the current server time, and transitions the experiment to running.
        Returns 400 if the experiment has already been launched or if the feature flag
        configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        launched_experiment = service.launch_experiment(experiment, request=request)
        return Response(ExperimentSerializer(launched_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def archive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Archive an ended experiment.

        Hides the experiment from the default list view. The experiment can be
        restored at any time by updating archived=false. Returns 400 if the
        experiment is already archived or has not ended yet.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        archived_experiment = service.archive_experiment(experiment, request=request)
        return Response(ExperimentSerializer(archived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def unarchive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Unarchive an archived experiment.

        Restores the experiment to the default list view. Returns 400 if the
        experiment is not currently archived.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        unarchived_experiment = service.unarchive_experiment(experiment, request=request)
        return Response(ExperimentSerializer(unarchived_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=EndExperimentSerializer,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        End a running experiment without shipping a variant.

        Sets end_date to now and marks the experiment as stopped. The feature
        flag is NOT modified — users continue to see their assigned variants
        and exposure events ($feature_flag_called) continue to be recorded.
        However, only data up to end_date is included in experiment results.

        Use this when:

        - You want to freeze the results window without changing which variant
          users see.
        - A variant was already shipped manually via the feature flag UI and
          the experiment just needs to be marked complete.

        The end_date can be adjusted after ending via PATCH if it needs to be
        backdated (e.g. to match when the flag was actually paused).

        Other options:
        - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
        - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

        Returns 400 if the experiment is not running.
        """
        experiment: Experiment = self.get_object()
        request_serializer = EndExperimentSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        ended_experiment = service.end_experiment(
            experiment,
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            request=request,
        )
        return Response(ExperimentSerializer(ended_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ShipVariantSerializer,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, url_path="ship_variant", required_scopes=["experiment:write"])
    def ship_variant(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Ship a variant to 100% of users and (optionally) end the experiment.

        Rewrites the feature flag so that the selected variant is served to everyone.
        Existing release conditions (flag groups) are preserved so the change can be
        rolled back by deleting the auto-added release condition in the feature flag UI.

        Can be called on both running and stopped experiments. If the experiment is
        still running, it will also be ended (end_date set and status marked as stopped).
        If the experiment has already ended, only the flag is rewritten - this supports
        the "end first, ship later" workflow.

        If an approval policy requires review before changes on the flag take effect,
        the API returns 409 with a change_request_id. The experiment is NOT ended until
        the change request is approved and the user retries.

        Returns 400 if the experiment is in draft state, the variant_key is not found
        on the flag, or the experiment has no linked feature flag.
        """
        experiment: Experiment = self.get_object()
        request_serializer = ShipVariantSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        service = ExperimentService(team=self.team, user=request.user)
        shipped_experiment = service.ship_variant(
            experiment,
            variant_key=request_serializer.validated_data["variant_key"],
            conclusion=request_serializer.validated_data.get("conclusion"),
            conclusion_comment=request_serializer.validated_data.get("conclusion_comment"),
            request=request,
        )
        return Response(ExperimentSerializer(shipped_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Pause a running experiment.

        Deactivates the linked feature flag so it is no longer returned by the
        /decide endpoint. Users fall back to the application default (typically
        the control experience), and no new exposure events are recorded (i.e.
        $feature_flag_called is not fired).
        Returns 400 if the experiment is not running or is already paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        paused_experiment = service.pause_experiment(experiment, request=request)
        return Response(ExperimentSerializer(paused_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Resume a paused experiment.

        Reactivates the linked feature flag so it is returned by /decide again.
        Users are re-bucketed deterministically into the same variants they had
        before the pause, and exposure tracking resumes.
        Returns 400 if the experiment is not running or is not paused.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        resumed_experiment = service.resume_experiment(experiment, request=request)
        return Response(ExperimentSerializer(resumed_experiment, context=self.get_serializer_context()).data)

    @extend_schema(
        request=None,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def reset(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Reset an experiment back to draft state.

        Clears start/end dates, conclusion, and archived flag. The feature
        flag is left unchanged — users continue to see their assigned variants.

        Previously collected events still exist but won't be included in
        results unless the start date is manually adjusted after re-launch.

        Returns 400 if the experiment is already in draft state.
        """
        experiment: Experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        reset_experiment = service.reset_experiment(experiment, request=request)
        return Response(ExperimentSerializer(reset_experiment, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def duplicate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Duplication is not supported for experiments using legacy metrics."},
                status=400,
            )

        feature_flag_key = request.data.get("feature_flag_key")
        name = request.data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        duplicate_experiment = service.duplicate_experiment(
            source_experiment,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=self.get_serializer_context(),
        )

        return Response(
            ExperimentSerializer(duplicate_experiment, context=self.get_serializer_context()).data, status=201
        )

    @extend_schema(
        request=CopyExperimentToProjectSerializer,
        responses=ExperimentSerializer,
    )
    @action(methods=["POST"], detail=True, url_path="copy_to_project", required_scopes=["experiment:write"])
    def copy_to_project(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: Experiment = self.get_object()

        if experiment_has_legacy_metrics(source_experiment):
            return Response(
                {"detail": "Copying is not supported for experiments using legacy metrics."},
                status=400,
            )

        request_serializer = CopyExperimentToProjectSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        target_team_id = request_serializer.validated_data["target_team_id"]
        target_team = Team.objects.filter(id=target_team_id, organization_id=self.team.organization_id).first()
        if target_team is None:
            return Response({"detail": "Target team not found."}, status=404)

        user_permissions = UserPermissions(user=cast(User, request.user))
        target_team_permissions = user_permissions.team(target_team)
        effective_level = target_team_permissions.effective_membership_level
        if effective_level is None or effective_level < OrganizationMembership.Level.MEMBER:
            return Response({"detail": "You do not have write access to the target project."}, status=403)

        feature_flag_key = request_serializer.validated_data.get("feature_flag_key")
        name = request_serializer.validated_data.get("name")

        service = ExperimentService(team=self.team, user=request.user)
        new_experiment = service.copy_experiment_to_project(
            source_experiment,
            target_team,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context={
                "request": request,
                "team_id": target_team.id,
                "project_id": target_team.project_id,
                "get_team": lambda: target_team,
            },
        )

        target_context = {
            **self.get_serializer_context(),
            "team_id": target_team.id,
            "project_id": target_team.project_id,
            "get_team": lambda: target_team,
        }
        return Response(ExperimentSerializer(new_experiment, context=target_context).data, status=201)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def create_exposure_cohort_for_experiment(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        service = ExperimentService(team=self.team, user=request.user)
        cohort = service.create_exposure_cohort(
            experiment,
            serializer_context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
            },
        )
        cohort_data = CohortSerializer(cohort, context={"request": request, "team": self.team}).data
        return Response({"cohort": cohort_data}, status=201)

    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def eligible_feature_flags(self, request: Request, **kwargs: Any) -> Response:
        """
        Returns a paginated list of feature flags eligible for use in experiments.

        Eligible flags must:
        - Be multivariate with at least 2 variants
        - Have "control" as the first variant key

        Query parameters:
        - search: Filter by flag key or name (case insensitive)
        - limit: Number of results per page (default: 20)
        - offset: Pagination offset (default: 0)
        - active: Filter by active status ("true" or "false")
        - created_by_id: Filter by creator user ID
        - order: Sort order field
        - evaluation_runtime: Filter by evaluation runtime
        - has_evaluation_contexts: Filter by presence of evaluation contexts ("true" or "false")
        """
        # validate limit and offset
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": "Invalid limit or offset"}, status=400)

        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
        excluded_flag_ids = survey_flag_ids | set(product_tour_internal_targeting_flags)

        service = ExperimentService(team=self.team, user=request.user)
        eligible_feature_flags = service.get_eligible_feature_flags(
            limit=limit,
            offset=offset,
            excluded_flag_ids=excluded_flag_ids,
            search=request.query_params.get("search"),
            active=request.query_params.get("active"),
            created_by_id=request.query_params.get("created_by_id"),
            order=request.query_params.get("order"),
            evaluation_runtime=request.query_params.get("evaluation_runtime"),
            has_evaluation_contexts=request.query_params.get("has_evaluation_contexts"),
        )

        # Serialize using the standard FeatureFlagSerializer
        serializer = FeatureFlagSerializer(
            eligible_feature_flags["results"],
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(
            {
                "results": serializer.data,
                "count": eligible_feature_flags["count"],
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="metric_uuid",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "UUID of the metric to fetch timeseries for. Available on each metric in the "
                    "experiment's metrics array."
                ),
                required=True,
            ),
            OpenApiParameter(
                name="fingerprint",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "Fingerprint of the metric configuration. Available alongside metric_uuid on "
                    "each metric in the experiment's metrics array."
                ),
                required=True,
            ),
        ],
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def timeseries_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        metric_uuid = request.query_params.get("metric_uuid")
        fingerprint = request.query_params.get("fingerprint")

        if not metric_uuid:
            raise ValidationError("metric_uuid query parameter is required")
        if not fingerprint:
            raise ValidationError("fingerprint query parameter is required")

        service = ExperimentService(team=self.team, user=request.user)
        return Response(service.get_timeseries_results(experiment, metric_uuid=metric_uuid, fingerprint=fingerprint))

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def recalculate_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()

        metric = request.data.get("metric")
        fingerprint = request.data.get("fingerprint")

        if not metric:
            raise ValidationError("metric is required")
        if not fingerprint:
            raise ValidationError("fingerprint is required")

        service = ExperimentService(team=self.team, user=request.user)
        result = service.request_timeseries_recalculation(experiment, metric=metric, fingerprint=fingerprint)
        is_existing = result.pop("is_existing", False)

        if not is_existing:
            recalculation_id = str(result["id"])
            try:
                temporal = sync_connect()
                asyncio.run(
                    temporal.start_workflow(
                        "experiment-timeseries-recalculation-workflow",
                        ExperimentTimeseriesRecalculationWorkflowInputs(recalculation_id=recalculation_id),
                        id=f"experiment-recalculation-{recalculation_id}",
                        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                    )
                )
            except Exception:
                ExperimentTimeseriesRecalculation.objects.filter(id=recalculation_id).update(
                    status=ExperimentTimeseriesRecalculation.Status.FAILED
                )
                raise

        status_code = 200 if is_existing else 201
        return Response(result, status=status_code)

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["experiment:read"])
    def stats(self, request: Request, **kwargs: Any) -> Response:
        service = ExperimentService(team=self.team, user=request.user)
        return Response(service.get_velocity_stats())


@mutable_receiver(model_activity_signal, sender=Experiment)
def handle_experiment_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if before_update and after_update:
        before_deleted = getattr(before_update, "deleted", None)
        after_deleted = getattr(after_update, "deleted", None)
        if before_deleted is not None and after_deleted is not None and before_deleted != after_deleted:
            activity = "restored" if after_deleted is False else "deleted"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update), name=after_update.name
        ),
    )
