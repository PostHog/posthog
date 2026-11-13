"""Actions for the timeseries results and the metrics recalculation runs of an experiment."""

import asyncio
from typing import Any, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.temporal import ExperimentTimeseriesRecalculationWorkflowInputs

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.backend.presentation.serializers.recalculation import (
    ExperimentMetricsRecalculationJobSerializer,
    ExperimentMetricsRecalculationLatestSerializer,
    ExperimentMetricsRecalculationRunSerializer,
    ExperimentTimeseriesResultsSerializer,
    RecalculateMetricsRequestSerializer,
)
from products.experiments.backend.recalculation import (
    build_job_payload,
    build_timeseries_cold_start_payload,
    exceeds_recalculation_age_limit,
    get_active_recalculation,
    get_latest_recalculation,
    get_recalculation_by_id,
    get_run_results,
    request_recalculation,
    start_metrics_recalculation_workflow,
)


class ExperimentRecalculationMixin(TeamAndOrgViewSetMixin):
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
                    "Ignored. The server derives the metric's calculation key from the experiment's current "
                    "settings. Accepted so that existing clients keep working."
                ),
                required=False,
                deprecated=True,
            ),
        ],
        responses={200: ExperimentTimeseriesResultsSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def timeseries_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        metric_uuid = request.query_params.get("metric_uuid")

        if not metric_uuid:
            raise ValidationError("metric_uuid query parameter is required")

        service = ExperimentService(team=self.team, user=request.user)
        return Response(
            ExperimentTimeseriesResultsSerializer(
                service.get_timeseries_results(experiment, metric_uuid=metric_uuid)
            ).data
        )

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def recalculate_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()

        # Only the metric's uuid is read, and a `fingerprint` in the body is ignored: the service derives the
        # definition and the key from the experiment.
        metric = request.data.get("metric")

        if not isinstance(metric, dict) or not metric:
            raise ValidationError("metric is required")

        service = ExperimentService(team=self.team, user=request.user)
        result = service.request_timeseries_recalculation(experiment, metric_uuid=metric.get("uuid") or "")
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
                # team-scoped filter: defense in depth so the rollback can never reach across teams even if
                # recalculation_id were ever sourced from somewhere less trusted than the row we just created.
                ExperimentTimeseriesRecalculation.objects.filter(team=self.team, id=recalculation_id).update(
                    status=ExperimentTimeseriesRecalculation.Status.FAILED
                )
                raise

        status_code = 200 if is_existing else 201
        return Response(result, status=status_code)

    @extend_schema(
        request=RecalculateMetricsRequestSerializer,
        responses={
            200: ExperimentMetricsRecalculationJobSerializer,
            201: ExperimentMetricsRecalculationJobSerializer,
            429: OpenApiResponse(
                description=(
                    "A manual trigger arrived less than five minutes after the latest completed run finished. "
                    "Retry-After carries the seconds until the next run is allowed."
                )
            ),
        },
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="metrics_recalculation",
        required_scopes=["experiment:write"],
    )
    def metrics_recalculation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Trigger a batch recalculation of all metrics for this experiment.

        Returns 201 with the new pending recalculation, or 200 with the active one if a recalculation is
        already pending or in progress for this experiment. An experiment that started too long ago gets 201 with
        a run that is already failed: every metric carries the `recalculation_window_too_long` error in
        `metric_errors`, no workflow starts, and a retry gets the same answer. A manual trigger within five
        minutes after the latest completed run finished returns 429 with a Retry-After header. The response payload intentionally does not
        include the `results` array — at POST time the workflow has just been queued and no per-metric
        results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
        progresses.
        """
        experiment: Experiment = self.get_object()
        request_serializer = RecalculateMetricsRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        is_mcp_client = request.headers.get("x-posthog-client") == "mcp"
        trigger = (
            ExperimentMetricsRecalculation.Trigger.AGENT_MCP
            if is_mcp_client
            else request_serializer.validated_data["trigger"]
        )

        # request.user is User | AnonymousUser at the DRF level; the viewset enforces auth so it's a User here.
        result = request_recalculation(experiment, cast(User, request.user), trigger)
        # Read without mutating — the serializer surfaces is_existing on the response so clients can detect
        # the idempotent-reuse path without inspecting the HTTP status code.
        is_existing = result.get("is_existing", False)

        # A rejected run is new but already FAILED, so it gets a 201 and no workflow.
        if not is_existing and result["status"] == ExperimentMetricsRecalculation.Status.PENDING:
            start_metrics_recalculation_workflow(
                str(result["id"]),
                team_id=experiment.team_id,
                organization_id=str(experiment.team.organization_id),
            )

        return Response(
            ExperimentMetricsRecalculationJobSerializer(result).data,
            status=200 if is_existing else 201,
        )

    @extend_schema(responses={200: ExperimentMetricsRecalculationLatestSerializer, 404: None})
    @action(
        methods=["GET"],
        detail=True,
        # NOTE: this action is declared BEFORE the by-id action so its URL pattern wins on /latest/.
        url_path="metrics_recalculation/latest",
        required_scopes=["experiment:read"],
    )
    def metrics_recalculation_latest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: Experiment = self.get_object()
        active = get_active_recalculation(experiment)
        active_run = {"id": str(active.id), "status": active.status} if active is not None else None
        recalc = get_latest_recalculation(experiment)

        if recalc is not None:
            return Response(_serialize_latest(experiment, _build_run_payload(recalc), active_run))

        # Cold start: no terminal run worth showing. Fall back to the latest timeseries data as a read-only
        # placeholder so the user sees results immediately, even while a first run is active (its pending
        # payload would blank them out); an active run still rides along for polling. Pure read, no
        # workflow start.
        fallback = build_timeseries_cold_start_payload(experiment)
        if fallback is not None:
            return Response(_serialize_latest(experiment, fallback, active_run))

        if active is not None:
            return Response(_serialize_latest(experiment, _build_run_payload(active), active_run))

        return Response({"detail": "No completed recalculation found"}, status=404)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="recalculation_id",
                location=OpenApiParameter.PATH,
                # Keep the URL's UUID pattern in the schema; declaring a bare UUID type drops it.
                type={
                    "type": "string",
                    "pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                },
                description=(
                    "UUID of the recalculation run to fetch. This is the run's own id, not the experiment id."
                ),
            )
        ],
        responses={200: ExperimentMetricsRecalculationRunSerializer, 404: None},
    )
    @action(
        methods=["GET"],
        detail=True,
        # Strict UUID regex so 'latest' (the sibling action above) never matches this route.
        url_path=r"metrics_recalculation/(?P<recalculation_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        required_scopes=["experiment:read"],
    )
    def metrics_recalculation_detail(
        self, request: Request, recalculation_id: str, *args: Any, **kwargs: Any
    ) -> Response:
        experiment: Experiment = self.get_object()
        recalc = get_recalculation_by_id(experiment, recalculation_id)
        if recalc is None:
            return Response({"detail": "Recalculation not found"}, status=404)
        return Response(ExperimentMetricsRecalculationRunSerializer(_build_run_payload(recalc)).data)


def _build_run_payload(recalc: ExperimentMetricsRecalculation) -> dict:
    results = get_run_results(recalc)
    payload = build_job_payload(recalc, results=results, include_live_progress=True)
    payload["results"] = results
    return payload


def _serialize_latest(experiment: Experiment, payload: dict, active_run: dict | None) -> dict:
    if active_run is not None:
        payload["active_run"] = active_run
    payload["exceeds_recalculation_age_limit"] = exceeds_recalculation_age_limit(experiment)
    return ExperimentMetricsRecalculationLatestSerializer(payload).data
