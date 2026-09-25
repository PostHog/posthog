from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse
from pydantic import JsonValue
from rest_framework import exceptions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.query_tagging import private_capture_context
from posthog.models import Team, User
from posthog.storage import object_storage
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_spend_gates
from products.signals.backend.scout_harness.skill_loader import SkillNotFoundError
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team
from products.signals.backend.scout_harness.trial_inspection import ScoutTrialInspection
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    create_trial_launch,
    read_trial_launch,
)
from products.signals.backend.scout_harness.trial_result import (
    export_trial_result,
    get_trial_workflow_status,
    read_trial_result,
    trial_result_key,
)
from products.signals.backend.scout_harness.trial_serializers import (
    ScoutTrialHistoryQuerySerializer,
    ScoutTrialHistorySerializer,
    ScoutTrialLaunchSerializer,
    ScoutTrialResultQuerySerializer,
    ScoutTrialResultSerializer,
    ScoutTrialSetupQuerySerializer,
    ScoutTrialSetupSerializer,
    ScoutTrialStartedSerializer,
)
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore


class ScoutTrialConfigMixin:
    team: Team

    def _internal_trial_config(self, request: Request, identifier: str) -> SignalScoutConfig:
        if self.team.id != 2 or not request.user.is_staff:
            raise exceptions.NotFound()
        return self._trial_config(request, identifier)

    def _trial_config(self, request: Request, identifier: str) -> SignalScoutConfig:
        if (
            isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication)
            and request.successful_authenticator.access_token.sandbox_task_id is not None
        ):
            raise exceptions.PermissionDenied("Scout runs cannot start or inspect operator trials.")
        team = self.team.parent_team or self.team
        if not UserAccessControl(user=cast(User, request.user), team=team).check_access_level_for_resource(
            "llm_skill", "editor"
        ):
            raise exceptions.PermissionDenied("Skill editor access is required to run scout variants.")
        try:
            config_id = UUID(identifier)
        except ValueError:
            raise exceptions.NotFound()
        config = (
            SignalScoutConfig.objects.for_team(team.id)
            .select_related("team", "team__organization")
            .filter(id=config_id)
            .first()
        )
        if config is None or config.skill_name in withheld_skills_for_team(team.id):
            raise exceptions.NotFound()
        return config

    @private_capture_context()
    @validated_request(
        query_serializer=ScoutTrialSetupQuerySerializer,
        responses={200: OpenApiResponse(response=ScoutTrialSetupSerializer)},
        operation_id="signals_scout_config_trial_setup",
        summary="Inspect a private scout comparison",
        description="Read comparison readiness and source settings for the internal comparison editor.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="trial_setup",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_setup(self, request: ValidatedRequest, **kwargs: str) -> Response:
        config = self._internal_trial_config(request, kwargs.get("id", ""))
        try:
            setup = ScoutTrialInspection(config, cast(User, request.user)).setup(
                request.validated_query_data.get("context_id")
            )
        except (ScoutTrialLaunchError, SkillNotFoundError) as error:
            raise exceptions.NotFound(str(error)) from error
        return Response(ScoutTrialSetupSerializer(setup).data)

    @private_capture_context()
    @validated_request(
        query_serializer=ScoutTrialHistoryQuerySerializer,
        responses={200: OpenApiResponse(response=ScoutTrialHistorySerializer)},
        operation_id="signals_scout_config_trial_history",
        summary="List your private scout comparison runs",
        description="Read recent private runs for the requesting operator in the internal comparison editor.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="trial_history",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_history(self, request: ValidatedRequest, **kwargs: str) -> Response:
        config = self._internal_trial_config(request, kwargs.get("id", ""))
        history = ScoutTrialInspection(config, cast(User, request.user)).history(request.validated_query_data["limit"])
        return Response(ScoutTrialHistorySerializer(history).data)

    @private_capture_context()
    @validated_request(
        request_serializer=ScoutTrialLaunchSerializer,
        responses={202: OpenApiResponse(response=ScoutTrialStartedSerializer)},
        operation_id="signals_scout_config_trial",
        summary="Run a private scout variant",
        description="Run a prompt, model, or effort variant against live data with private memory and report capture.",
    )
    @action(detail=True, methods=["post"], url_path="trial")
    def trial(self, request: ValidatedRequest, **kwargs: str) -> Response:
        config = self._trial_config(request, kwargs.get("id", ""))
        for rejection in (check_fleet_gates(config.team_id), check_spend_gates(config.team, capture_analytics=False)):
            if rejection is not None:
                if rejection.kind.value == "throttled":
                    raise exceptions.Throttled(detail=rejection.detail)
                raise exceptions.PermissionDenied(rejection.detail)
        try:
            launch = create_trial_launch(config=config, user=cast(User, request.user), **request.validated_data)
        except (ScoutTrialLaunchError, SkillNotFoundError) as error:
            raise exceptions.ValidationError({"detail": str(error)})

        # Dispatch imports the worker graph, which is unnecessary during API route loading.
        from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
            start_trial_signals_scout_run,
        )

        workflow_id = start_trial_signals_scout_run(
            sync_connect(), team_id=config.team_id, skill_name=config.skill_name, launch_id=str(launch.id)
        )
        return Response(
            ScoutTrialStartedSerializer(
                {
                    "launch_id": launch.id,
                    "context_id": launch.context_id,
                    "workflow_id": workflow_id,
                    "model": launch.model,
                    "reasoning_effort": launch.reasoning_effort,
                    "variant": launch.variant,
                }
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @private_capture_context()
    @validated_request(
        query_serializer=ScoutTrialResultQuerySerializer,
        responses={200: OpenApiResponse(response=ScoutTrialResultSerializer)},
        operation_id="signals_scout_config_trial_result",
        summary="Read a private scout trial result",
        description="Read a trial's existing run status and its privately captured reports and memory changes.",
    )
    @action(detail=True, methods=["get"], url_path="trial_result")
    def trial_result(self, request: ValidatedRequest, **kwargs: str) -> Response:
        config = self._trial_config(request, kwargs.get("id", ""))
        identifier = request.validated_query_data["launch_id"]
        try:
            launch = read_trial_launch(config.team_id, identifier)
        except ScoutTrialLaunchError as launch_error:
            raise exceptions.NotFound() from launch_error
        if launch.config_id != config.id or launch.user_id != request.user.pk:
            raise exceptions.NotFound()
        run = (
            SignalScoutRun.objects.for_team(config.team_id)
            .filter(
                scout_config_id=config.id,
                metadata__scout_trial__launch_id=str(identifier),
                task_run__task__created_by=request.user,
            )
            .select_related("task_run", "task_run__task")
            .first()
        )
        reports: list[JsonValue] = []
        memory: JsonValue = {}
        invalid_reason = None
        result_key = None
        export_error = None
        error = None
        trial_status = run.task_run.status if run else "pending"
        saved_result = None
        if run is not None:
            try:
                saved_result = read_trial_result(run)
                if saved_result is None and run.task_run.status in {"completed", "failed", "cancelled"}:
                    result_key = export_trial_result(run)
                    saved_result = read_trial_result(run)
                if saved_result is not None:
                    result_key = trial_result_key(run)
                    trial_status = cast(str, saved_result["status"])
            except (object_storage.ObjectStorageError, ValueError):
                export_error = "The result export failed. Retry this request to save it again."
        if saved_result is None and (run is None or run.task_run.status in {"queued", "in_progress"}):
            workflow = get_trial_workflow_status(team_id=config.team_id, launch_id=launch.id)
            if run is None:
                trial_status = "pending" if workflow.status == "completed" and workflow.run_id else workflow.status
                error = workflow.error
            elif workflow.status in {"failed", "cancelled", "skipped"}:
                trial_status = workflow.status
                error = workflow.error
                ScoutTrialStore(run).invalidate(
                    error or "The controlling scout workflow ended before its task.", allow_terminal=True
                )
        usage: dict[str, JsonValue] = {}
        if run is not None:
            private = ScoutTrialStore(run).export()
            stored_reports = private["reports"]
            reports = list(stored_reports.values()) if isinstance(stored_reports, dict) else []
            memory = private["memory"]
            invalid_reason = private["invalid_reason"]
            token_usage = (run.task_run.state or {}).get("token_usage")
            if isinstance(token_usage, dict):
                usage = token_usage
        return Response(
            ScoutTrialResultSerializer(
                {
                    "launch_id": identifier,
                    "context_id": launch.context_id,
                    "model": launch.model,
                    "reasoning_effort": launch.reasoning_effort,
                    "skill_body_sha256": hashlib.sha256(launch.skill_body.encode()).hexdigest(),
                    "result_key": result_key,
                    "export_error": export_error,
                    "started_at": run.task_run.created_at if run else None,
                    "completed_at": run.task_run.completed_at if run else None,
                    "run_id": run.id if run else None,
                    "task_id": run.task_run.task_id if run else None,
                    "task_run_id": run.task_run_id if run else None,
                    "status": trial_status,
                    "task_status": run.task_run.status if run else None,
                    "error": error,
                    "summary": run.summary if run else "",
                    "invalid_reason": invalid_reason,
                    "reports": reports,
                    "memory": memory,
                    "cost_usd": None,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            ).data
        )
