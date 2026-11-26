from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

from products.experiments.backend.metric_calculation.config import (
    CALCULATION_KEY_VERSION,
    find_calculation_config_by_key,
)
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.backend.timeseries_backfill import backfill_experiment_timeseries


def seed_master_demo_timeseries(team_id: int, request_id: str, until: date) -> None:
    request = ExperimentTimeseriesRecalculation.objects.select_related("experiment").get(pk=request_id, team_id=team_id)
    experiment = request.experiment
    config = find_calculation_config_by_key(experiment, request.metric["uuid"], request.fingerprint)
    if config is not None:
        # Cross-team reuse also needs the team-level calculation settings omitted by legacy keys.
        request.fingerprint = config.key_for_version(CALCULATION_KEY_VERSION)
        request.save(update_fields=["fingerprint"])
    backfill_experiment_timeseries(str(request.id), backfill_until=until)


def seed_cloned_demo_timeseries(source_team_id: int, team_id: int, request_id: str, until: date) -> None:
    target = ExperimentTimeseriesRecalculation.objects.get(pk=request_id, team_id=team_id)
    if not copy_demo_timeseries(source_team_id, target, until):
        backfill_experiment_timeseries(str(target.id), backfill_until=until)


def copy_demo_timeseries(source_team_id: int, target: ExperimentTimeseriesRecalculation, until: date) -> bool:
    experiment = Experiment.objects.select_related("team", "feature_flag").get(
        pk=target.experiment_id, team_id=target.team_id
    )
    target_config = find_calculation_config_by_key(experiment, target.metric["uuid"], target.fingerprint)
    if target_config is None or experiment.start_date is None:
        return False
    source = (
        ExperimentTimeseriesRecalculation.objects.filter(
            team_id=source_team_id,
            fingerprint=target_config.key_for_version(CALCULATION_KEY_VERSION),
            experiment__feature_flag__key=experiment.feature_flag.key,
            experiment__start_date=experiment.start_date,
            status=ExperimentTimeseriesRecalculation.Status.COMPLETED,
            last_successful_date=until,
            metric__name=target.metric["name"],
        )
        .order_by("-created_at")
        .first()
    )
    if source is None:
        return False

    team_timezone = ZoneInfo(experiment.team.timezone or "UTC")
    start = experiment.start_date.astimezone(team_timezone).date()
    windows = {
        datetime.combine(start + timedelta(days=offset + 1), time.min, team_timezone)
        for offset in range((until - start).days + 1)
    }
    points = ExperimentMetricResult.objects.filter(
        experiment_id=source.experiment_id,
        metric_uuid=source.metric["uuid"],
        fingerprint=source.fingerprint,
        status=ExperimentMetricResult.Status.COMPLETED,
        query_from=experiment.start_date,
        query_to__in=windows,
    )
    copies = [
        ExperimentMetricResult(
            experiment=experiment,
            metric_uuid=target.metric["uuid"],
            fingerprint=target.fingerprint,
            display_key=target_config.legacy_key(),
            query_from=point.query_from,
            query_to=point.query_to,
            status=point.status,
            completed_at=point.completed_at,
            # Debug queries name the source team and cannot be run against this clone.
            result={**point.result, "clickhouse_sql": None, "hogql": None},
        )
        for point in points
        if isinstance(point.result, dict)
    ]
    if not windows or len(copies) != len(windows):
        return False

    with transaction.atomic():
        ExperimentMetricResult.objects.bulk_create(copies)
        target.status = ExperimentTimeseriesRecalculation.Status.COMPLETED
        target.last_successful_date = until
        target.save(update_fields=["status", "last_successful_date"])
    return True
