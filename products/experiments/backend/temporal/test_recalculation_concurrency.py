from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from time import monotonic

import pytest
import time_machine
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.utils import timezone

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import request_recalculation
from products.experiments.backend.temporal.recalculation_logic import _store_result
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing_result", [False, True])
@time_machine.travel("2026-09-01T12:00:00Z", tick=False)
def test_superseded_result_cannot_overwrite_a_replacement_during_commit(
    team: Team, user: User, existing_result: bool
) -> None:
    query_to = timezone.now()
    query_from = query_to - timedelta(days=2)
    experiment = Experiment.objects.create(
        team=team,
        name="Concurrent recalculation",
        feature_flag=FeatureFlag.objects.create(team=team, key="concurrent-recalculation"),
        start_date=query_from,
        end_date=query_to,
    )
    stale = ExperimentMetricsRecalculation.objects.for_team(team.id).create(
        team=team,
        experiment=experiment,
        status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
        started_at=query_to - timedelta(hours=2),
        query_to=query_to,
    )
    result_key = {"experiment_id": experiment.id, "metric_uuid": "m1", "query_to": query_to}
    if existing_result:
        ExperimentMetricResult.objects.create(
            **result_key, fingerprint="previous", query_from=query_from, result={"previous": True}
        )

    worker_pid: Queue[int] = Queue()

    def store_stale_result() -> None:
        try:
            with team_scope(team.id, canonical=True), connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.put(cursor.fetchone()[0])
                _store_result(
                    recalculation_id=str(stale.id),
                    experiment_id=experiment.id,
                    metric_uuid="m1",
                    query_to=query_to,
                    recalc_fp="stale",
                    query_from=query_from,
                    status=ExperimentMetricResult.Status.FAILED,
                    result=None,
                    error_message="abandoned calculation failed",
                )
        finally:
            connections.close_all()

    with (
        patch("products.experiments.backend.recalculation._cancel_superseded_workflows"),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        with transaction.atomic():
            request_recalculation(experiment, user)
            ExperimentMetricResult.objects.update_or_create(
                experiment_id=experiment.id,
                metric_uuid="m1",
                query_to=query_to,
                defaults={
                    "fingerprint": "replacement",
                    "query_from": query_from,
                    "status": ExperimentMetricResult.Status.COMPLETED,
                    "result": {"fresh": True},
                },
            )
            writer = executor.submit(store_stale_result)
            pid = worker_pid.get(timeout=5)
            deadline = monotonic() + 5
            with connection.cursor() as cursor:
                while True:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [pid])
                    if cursor.fetchone()[0]:
                        break
                    assert not writer.done(), "stale writer finished before the replacement committed"
                    assert monotonic() < deadline, "stale writer did not reach the concurrent write"
        writer.result(timeout=5)

    result = ExperimentMetricResult.objects.get(**result_key)
    assert result.status == ExperimentMetricResult.Status.COMPLETED
    assert result.fingerprint == "replacement"
    assert result.result == {"fresh": True}
    assert result.error_message is None
