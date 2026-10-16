from datetime import datetime

from django.db import models

from rest_framework.exceptions import ValidationError

from posthog.schema import CachedExperimentExposureQueryResponse, ExperimentExposureHealthFinding

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.user import User

from products.experiments.backend.health.context import ExposureTotals
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import (
    ExperimentExposuresQueryRunner,
    build_experiment_exposure_query,
)
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.models.experiment import Experiment


class HealthExposureInputsStatus(models.TextChoices):
    READY = "ready"
    # The cached answer is past its age. A recalculation runs in the background.
    STALE = "stale"
    # No cached answer. A calculation runs in the background.
    CALCULATING = "calculating"
    NOT_LAUNCHED = "not_launched"
    NO_QUERY_ACCESS = "no_query_access"
    FAILED = "failed"


@frozen
class ExposureInputs:
    """The exposure query's answer that the exposure checks of the health engine read, and their findings on it."""

    status: HealthExposureInputsStatus
    # When the answer was computed. None without an answer.
    computed_at: datetime | None
    totals: ExposureTotals | None
    findings: tuple[ExperimentExposureHealthFinding, ...]
    # Why the query failed, for FAILED.
    error: str | None


def load_exposure_inputs(experiment: Experiment, *, user: User | None, can_query_events: bool) -> ExposureInputs:
    """
    Reads the cached answer of the experiment's exposure query. A missing or stale answer starts a calculation in the
    background instead of blocking, because the query can run for minutes. Never raises.
    """
    if experiment.start_date is None:
        return _without_answer(HealthExposureInputsStatus.NOT_LAUNCHED)
    if not can_query_events:
        return _without_answer(HealthExposureInputsStatus.NO_QUERY_ACCESS)
    query = build_experiment_exposure_query(experiment)
    try:
        runner = ExperimentExposuresQueryRunner(query=query, team=experiment.team, user=user, error_event_context=None)
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE, user=user)
    except Exception as error:
        # A running experiment whose flag lost its variants raises a ValidationError, which is expected.
        if not isinstance(error, ValidationError):
            capture_exception(error)
        return _without_answer(HealthExposureInputsStatus.FAILED, error=_error_message(error))
    if not isinstance(response, CachedExperimentExposureQueryResponse):
        return _without_answer(HealthExposureInputsStatus.CALCULATING)

    recalculating = response.query_status is not None and not response.query_status.complete
    srm = response.sample_ratio_mismatch
    computed_at = response.last_refresh
    return ExposureInputs(
        status=HealthExposureInputsStatus.STALE if recalculating else HealthExposureInputsStatus.READY,
        computed_at=computed_at,
        totals=ExposureTotals(
            # The schema types the counts as floats, but the runner computes whole people.
            total_exposures={variant: int(count) for variant, count in response.total_exposures.items()},
            # The runner resolves the handling the same way when it computes the answer.
            multiple_variant_handling=get_exposure_config_params_for_builder(
                query.exposure_criteria, experiment.team, experiment.start_date
            ).multiple_variant_handling,
            sample_ratio_mismatch_p_value=srm.p_value if srm else None,
            # The checks read the hours at computation, not now.
            hours_since_launch=(computed_at - experiment.start_date).total_seconds() / 3600 if computed_at else None,
        ),
        findings=tuple(response.health_findings or ()),
        error=None,
    )


def _without_answer(status: HealthExposureInputsStatus, *, error: str | None = None) -> ExposureInputs:
    return ExposureInputs(status=status, computed_at=None, totals=None, findings=(), error=error)


def _error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        details = error.detail if isinstance(error.detail, list) else [error.detail]
        return " ".join(str(detail) for detail in details)
    return str(error)
