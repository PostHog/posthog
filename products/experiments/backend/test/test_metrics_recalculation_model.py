from datetime import UTC, datetime

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.utils import uuid7

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Status = ExperimentMetricsRecalculation.Status


class TestExperimentMetricsRecalculationModel(BaseTest):
    def _flag(self, key: str | None = None) -> FeatureFlag:
        # Unique key per call (BaseTest rolls back between methods, but the helper's default key would still
        # collide if two tests in the same transaction reused it). Full uuid7 hex — the truncated form
        # collides for back-to-back calls because uuid7's leading bytes are millisecond-aligned.
        key = key or f"recalc-flag-{uuid7().hex}"
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

    def _experiment(self, flag_key: str | None = None) -> Experiment:
        return Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag(flag_key), name="exp"
        )

    def test_defaults(self):
        with team_scope(self.team.id, canonical=True):
            recalc = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=self._experiment())
            assert recalc.status == Status.PENDING
            assert recalc.total_metrics == 0
            assert recalc.metric_errors == {}
            assert recalc.metric_uuids == []
            assert recalc.trigger == ExperimentMetricsRecalculation.Trigger.MANUAL
            assert recalc.started_at is None
            assert recalc.completed_at is None
            assert recalc.query_to is None

    @parameterized.expand(
        [
            (Status.PENDING, True),
            (Status.IN_PROGRESS, True),
            (Status.COMPLETED, False),
            (Status.FAILED, False),
        ]
    )
    def test_active_recalculation_uniqueness(self, existing_status: str, should_block: bool):
        exp = self._experiment(flag_key=f"recalc-uniq-{existing_status}")
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=existing_status)

            def _create_second() -> None:
                ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=Status.PENDING)

            if should_block:
                with self.assertRaises(IntegrityError), transaction.atomic():
                    _create_second()
            else:
                _create_second()
                assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 2

    def test_timestamps_and_window_round_trip(self):
        # Pin storage behavior for the lifecycle timestamps and the shared data-window end. The "set once
        # on start" invariant for query_to is enforced by the workflow's start-progress activity (covered
        # in PR2's activity tests); this test just confirms the model stores and returns the values intact.
        started = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 6, 3, 12, 5, 0, tzinfo=UTC)
        query_to = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
        with team_scope(self.team.id, canonical=True):
            recalc = ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=self._experiment(),
                started_at=started,
                completed_at=completed,
                query_to=query_to,
                status=Status.COMPLETED,
            )
            recalc.refresh_from_db()
            assert recalc.started_at == started
            assert recalc.completed_at == completed
            assert recalc.query_to == query_to

    def test_created_by_nullable_and_survives_user_deletion(self):
        # created_by is on_delete=SET_NULL: explicit None on create works, and deleting the user later
        # nulls the FK without cascading to the recalc row.
        from posthog.models import User

        another_user = User.objects.create_user(
            email=f"recalc-author-{uuid7().hex}@example.com", password=None, first_name="Author"
        )
        with team_scope(self.team.id, canonical=True):
            # Explicit None on create.
            null_recalc = ExperimentMetricsRecalculation.objects.create(
                team=self.team, experiment=self._experiment(), created_by=None
            )
            assert null_recalc.created_by is None

            # SET_NULL on user deletion.
            owned_recalc = ExperimentMetricsRecalculation.objects.create(
                team=self.team, experiment=self._experiment(), created_by=another_user
            )
            owned_recalc_id = owned_recalc.id

        another_user.delete()
        with team_scope(self.team.id, canonical=True):
            owned_recalc.refresh_from_db()
            assert owned_recalc.created_by is None
            assert ExperimentMetricsRecalculation.objects.filter(id=owned_recalc_id).exists()
