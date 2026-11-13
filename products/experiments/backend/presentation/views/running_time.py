"""Actions for the running time target and the running time calculator."""

from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.experiments.backend.facade.api import get_running_time_target
from products.experiments.backend.facade.contracts import RunningTimeMode

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.serializers.running_time import (
    RunningTimeCalculationInputSerializer,
    RunningTimeCalculationResultSerializer,
    RunningTimeTargetQuerySerializer,
    RunningTimeTargetSerializer,
)
from products.experiments.backend.running_time_calculator import (
    BaselineStats,
    calculate_baseline_value,
    calculate_running_time_days,
    calculate_sample_size,
    calculate_variance,
    calculate_variance_from_stats,
)


class ExperimentRunningTimeMixin(TeamAndOrgViewSetMixin):
    @validated_request(
        query_serializer=RunningTimeTargetQuerySerializer,
        responses={200: OpenApiResponse(response=RunningTimeTargetSerializer)},
    )
    @action(methods=["GET"], detail=True, url_path="running_time_target", required_scopes=["experiment:read"])
    def running_time_target(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """The target sample of the experiment's running time estimate, which the experiment page's header compares
        with the exposures so far, and what the experiment can detect over time.

        In manual running time mode it is the saved target. Otherwise it is sized from the first primary metric's
        current result: the variance the analysis uses (with CUPED when the analysis applied it) and the flag's
        traffic split, so that the comparison of each variant with the control reaches the minimum detectable effect.
        """
        experiment: Experiment = self.get_object()
        target = get_running_time_target(
            team_id=self.team.id,
            experiment_id=experiment.id,
            mode=RunningTimeMode(mode) if (mode := request.validated_query_data.get("mode")) else None,
        )
        return Response(RunningTimeTargetSerializer(target).data)

    @validated_request(
        request_serializer=RunningTimeCalculationInputSerializer,
        responses={200: OpenApiResponse(response=RunningTimeCalculationResultSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="calculate_running_time",
        required_scopes=["experiment:read"],
    )
    def calculate_running_time(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Estimate the recommended sample size and running time for an experiment.

        Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
        minimum detectable effect, and either a baseline value or raw baseline statistics. When
        `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
        """
        data = request.validated_data
        metric_type = data["metric_type"]
        mde = data["minimum_detectable_effect"]
        number_of_variants = data["number_of_variants"]
        exposure_rate = data.get("exposure_rate_per_day")

        baseline: BaselineStats | None = None
        stats = data.get("baseline_stats")
        if stats is not None:
            baseline = BaselineStats(
                number_of_samples=stats["number_of_samples"],
                sum=stats["sum"],
                sum_squares=stats.get("sum_squares", 0.0),
                denominator_sum=stats.get("denominator_sum"),
                denominator_sum_squares=stats.get("denominator_sum_squares"),
                numerator_denominator_sum_product=stats.get("numerator_denominator_sum_product"),
                step_counts=stats.get("step_counts") or [],
            )

        baseline_value = data.get("baseline_value")
        if baseline_value is None and baseline is not None:
            baseline_value = calculate_baseline_value(baseline, metric_type)

        variance = data.get("variance")
        if variance is None and baseline_value is not None:
            if baseline is not None:
                variance = calculate_variance_from_stats(baseline_value, metric_type, baseline)
            else:
                variance = calculate_variance(metric_type, baseline_value)

        recommended_sample_size: int | None = None
        if baseline_value is not None:
            recommended_sample_size = calculate_sample_size(
                metric_type, baseline_value, mde, number_of_variants, variance
            )

        # nosemgrep: api-response-must-match-schema -- moved unchanged from presentation/views.py
        return Response(
            {
                "baseline_value": baseline_value,
                "variance": variance,
                "recommended_sample_size": recommended_sample_size,
                "recommended_running_time_days": calculate_running_time_days(recommended_sample_size, exposure_rate),
            }
        )
