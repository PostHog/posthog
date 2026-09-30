from __future__ import annotations

from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.clickhouse.query_tagging import private_capture_context
from posthog.models import User

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.trial_comparison_serializers import (
    ScoutTrialComparisonHistorySerializer,
    ScoutTrialComparisonQuerySerializer,
    ScoutTrialComparisonRequestSerializer,
    ScoutTrialComparisonSerializer,
)
from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonRequest
from products.signals.backend.scout_harness.trial_launch import ScoutTrialLaunchError
from products.signals.backend.scout_harness.trial_serializers import ScoutTrialHistoryQuerySerializer


class ScoutTrialComparisonMixin:
    def _internal_trial_config(self, request: Request, identifier: str) -> SignalScoutConfig:
        raise NotImplementedError

    @private_capture_context()
    @validated_request(
        request_serializer=ScoutTrialComparisonRequestSerializer,
        responses={202: OpenApiResponse(response=ScoutTrialComparisonSerializer)},
        operation_id="signals_scout_config_trial_comparison_create",
        summary="Run and judge a private scout comparison",
        description="Freeze variants and the reviewed rubric, then run scouts and judge their results in the background.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="trial_comparison",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_comparison_create(self, request: ValidatedRequest, **kwargs: str) -> Response:
        from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- avoid loading the judge and worker graph at route discovery
            ScoutTrialComparisons,
        )
        from products.signals.backend.temporal.agentic.scout_trial_comparison import (  # noqa: PLC0415 -- worker graph is only needed for dispatch
            start_trial_comparison,
        )

        config = self._internal_trial_config(request, kwargs.get("id", ""))
        service = ScoutTrialComparisons(config, cast(User, request.user))
        try:
            plan = service.create(TrialComparisonRequest.model_validate(request.validated_data))
            result = service.result(plan, inspect_workflow=False, starting=True)
            if result.status != "completed":
                start_trial_comparison(config.team_id, plan.comparison_id)
        except ScoutTrialLaunchError as error:
            raise exceptions.ValidationError({"detail": str(error)}) from error
        return Response(
            ScoutTrialComparisonSerializer(result.model_dump(mode="json")).data, status=status.HTTP_202_ACCEPTED
        )

    @private_capture_context()
    @validated_request(
        request_serializer=ScoutTrialComparisonQuerySerializer,
        responses={202: OpenApiResponse(response=ScoutTrialComparisonSerializer)},
        operation_id="signals_scout_config_trial_comparison_resume",
        summary="Resume a saved scout comparison",
        description="Recover the same comparison without repeating saved scout runs or judge attempts.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="trial_comparison_resume",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_comparison_resume(self, request: ValidatedRequest, **kwargs: str) -> Response:
        from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- avoid loading the judge and worker graph at route discovery
            ScoutTrialComparisons,
        )
        from products.signals.backend.temporal.agentic.scout_trial_comparison import (  # noqa: PLC0415 -- worker graph is only needed for dispatch
            start_trial_comparison,
        )

        config = self._internal_trial_config(request, kwargs.get("id", ""))
        service = ScoutTrialComparisons(config, cast(User, request.user))
        try:
            plan = service.read(request.validated_data["comparison_id"])
        except ScoutTrialLaunchError as error:
            raise exceptions.NotFound() from error
        try:
            result = service.result(plan, inspect_workflow=False, starting=True)
            if result.status != "completed":
                service.assert_can_start()
                start_trial_comparison(config.team_id, plan.comparison_id)
        except ScoutTrialLaunchError as error:
            raise exceptions.ValidationError({"detail": str(error)}) from error
        return Response(
            ScoutTrialComparisonSerializer(result.model_dump(mode="json")).data, status=status.HTTP_202_ACCEPTED
        )

    @private_capture_context()
    @validated_request(
        query_serializer=ScoutTrialComparisonQuerySerializer,
        responses={200: OpenApiResponse(response=ScoutTrialComparisonSerializer)},
        operation_id="signals_scout_config_trial_comparison_retrieve",
        summary="Read a saved scout comparison",
        description="Read comparison progress and its saved report without starting any scout or judge calls.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="trial_comparison_result",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_comparison_retrieve(self, request: ValidatedRequest, **kwargs: str) -> Response:
        from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- avoid loading the judge and worker graph at route discovery
            ScoutTrialComparisons,
        )

        config = self._internal_trial_config(request, kwargs.get("id", ""))
        service = ScoutTrialComparisons(config, cast(User, request.user))
        try:
            result = service.result(service.read(request.validated_query_data["comparison_id"]))
        except ScoutTrialLaunchError as error:
            raise exceptions.NotFound() from error
        return Response(ScoutTrialComparisonSerializer(result.model_dump(mode="json")).data)

    @private_capture_context()
    @validated_request(
        query_serializer=ScoutTrialHistoryQuerySerializer,
        responses={200: OpenApiResponse(response=ScoutTrialComparisonHistorySerializer)},
        operation_id="signals_scout_config_trial_comparison_history",
        summary="List your saved scout comparisons",
        description="Read recent comparisons, including those saved before any scout run started.",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="trial_comparison_history",
        required_scopes=["signal_scout:write", "llm_skill:write"],
    )
    def trial_comparison_history(self, request: ValidatedRequest, **kwargs: str) -> Response:
        from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- avoid loading the judge and worker graph at route discovery
            ScoutTrialComparisons,
        )

        config = self._internal_trial_config(request, kwargs.get("id", ""))
        history = ScoutTrialComparisons(config, cast(User, request.user)).history(request.validated_query_data["limit"])
        return Response(ScoutTrialComparisonHistorySerializer(history.model_dump(mode="json")).data)
