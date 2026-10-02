"""The per-variant readout of an experiment scanner, counted from its observations.

Counts are read from Postgres on every call, so they never lag the observations.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from django.db.models import Aggregate, Count, FloatField, Max, Min, Q
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ReplayObservation,
    hydrate_for_serialization,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scanner_access import accessible_observations

if TYPE_CHECKING:
    from products.experiments.backend.facade.contracts import ExperimentPromptContext, ExperimentStatus

# The `variant` filter value for observations with no attributed variant. Variant keys are flag variant
# keys, so a name with this shape can't collide with a real one in practice.
UNATTRIBUTED_VARIANT = "__unattributed__"
LATEST_OBSERVATIONS_PER_VARIANT = 2


class _Median(Aggregate):
    function = "percentile_cont"
    template = "%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()


@frozen
class VariantsExperiment:
    id: int
    name: str
    status: str
    start_date: datetime | None
    end_date: datetime | None
    planned_duration_days: float | None
    # The experiment's day number: 1 on its launch day, frozen once it ends.
    current_day: int | None


@frozen
class VariantsWindow:
    total_observations: int
    first_observation_at: datetime | None
    last_observation_at: datetime | None


@frozen
class VariantReadout:
    key: str
    observations: int
    distinct_people: int
    median_session_duration_s: float | None
    sampling_rate: float | None
    latest_observations: tuple[ReplayObservation, ...]


@frozen
class ExperimentVariantsReadout:
    experiment: VariantsExperiment | None
    window: VariantsWindow
    variants: tuple[VariantReadout, ...]
    unattributed_count: int


def experiment_variants_readout(
    scanner: ReplayScanner, *, access: UserAccessControl, viewer_id: int | None
) -> ExperimentVariantsReadout:
    """The readout for an experiment scanner the caller may already read (see `scanner_for_recording_derived_read`)."""
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from products.experiments.backend.facade.replay import experiment_prompt_context, experiment_status  # noqa: PLC0415

    scope = scanner.experiment_scope() or {}
    experiment_id = scope.get("experiment_id")
    context = experiment_prompt_context(scanner.team, experiment_id=experiment_id) if experiment_id else None
    status = experiment_status(scanner.team, experiment_id=experiment_id) if experiment_id else None

    # `->>` reads both a missing key and a JSON null as SQL NULL, so rows scanned before attribution
    # shipped and rows written with an explicit null both land in `variant__isnull=True`.
    observations = accessible_observations(
        access,
        scanner.team_id,
        ReplayObservation.objects.filter(team_id=scanner.team_id, scanner=scanner, status=ObservationStatus.SUCCEEDED),
    ).annotate(variant=KT("scanner_result__experiment_variant"))
    window = observations.aggregate(
        total=Count("id"),
        unattributed=Count("id", filter=Q(variant__isnull=True)),
        first=Min("completed_at"),
        last=Max("completed_at"),
    )
    attributed = observations.filter(variant__isnull=False)
    stats = {
        row["variant"]: row
        for row in attributed.values("variant").annotate(
            observations=Count("id"),
            distinct_people=Count("distinct_id", distinct=True),
            median_duration=_Median(Cast(KT("scanner_result__session_duration_s"), FloatField())),
        )
    }

    # Watched variants first, in the scanner's order, so a variant with no observations yet still shows.
    # A key seen in observations but no longer watched (the selection changed) follows them.
    configured = scope.get("variants")
    watched = list(configured) if configured else [variant.key for variant in context.variants] if context else []
    keys = watched + sorted(key for key in stats if key not in watched)

    variants = []
    for key in keys:
        row = stats.get(key)
        latest = tuple(
            hydrate_for_serialization(attributed.filter(variant=key), viewer_id=viewer_id).order_by("-completed_at")[
                :LATEST_OBSERVATIONS_PER_VARIANT
            ]
        )
        variants.append(
            VariantReadout(
                key=key,
                observations=row["observations"] if row else 0,
                distinct_people=row["distinct_people"] if row else 0,
                median_session_duration_s=row["median_duration"] if row else None,
                sampling_rate=_sampling_rate(latest[0], key) if latest else None,
                latest_observations=latest,
            )
        )

    return ExperimentVariantsReadout(
        experiment=_experiment(context, status),
        window=VariantsWindow(
            total_observations=window["total"],
            first_observation_at=window["first"],
            last_observation_at=window["last"],
        ),
        variants=tuple(variants),
        unattributed_count=window["unattributed"],
    )


def _sampling_rate(observation: ReplayObservation, key: str) -> float | None:
    """The rate the variant was sampled at by the tick that scanned its latest observation.

    Balanced sampling records a rate per variant; without it every variant shared the scanner's rate.
    """
    snapshot = observation.scanner_snapshot if isinstance(observation.scanner_snapshot, dict) else {}
    rates = snapshot.get("variant_sampling_rates")
    if isinstance(rates, dict) and isinstance(rates.get(key), int | float):
        return float(rates[key])
    rate = snapshot.get("sampling_rate")
    return float(rate) if isinstance(rate, int | float) else None


def _experiment(
    context: "ExperimentPromptContext | None", status: "ExperimentStatus | None"
) -> VariantsExperiment | None:
    if context is None or status is None:
        return None
    current_day = None
    if status.start_date is not None:
        until = min(timezone.now(), status.end_date) if status.end_date is not None else timezone.now()
        current_day = max((until - status.start_date).days + 1, 1)
    return VariantsExperiment(
        id=context.id,
        name=context.name,
        status=status.status,
        start_date=status.start_date,
        end_date=status.end_date,
        planned_duration_days=status.planned_duration_days,
        current_day=current_day,
    )
