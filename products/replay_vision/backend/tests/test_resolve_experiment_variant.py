from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.persons import create_person

from products.replay_vision.backend.error_kinds import IneligibleSessionKind
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_backfill import ReplayScannerBackfill
from products.replay_vision.backend.temporal.activities.resolve_experiment_variant import _resolve
from products.replay_vision.backend.temporal.errors import FailureKind, IneligibleSessionError, ScannerFailureError
from products.replay_vision.backend.temporal.types import ResolveExperimentVariantInputs
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for

FROZEN_NOW = "2026-01-10T20:00:00Z"
BASE_TIME = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)


def _launched_experiment(test: BaseTest, key: str, variants: list[str]):
    # The helper launches "now"; exposures in these tests happen at BASE_TIME, so the experiment
    # must have started before them or every session reads as unexposed.
    experiment = create_experiment(test.team, key, launched=True, variants=variants)
    experiment.start_date = BASE_TIME - timedelta(days=1)
    experiment.save()
    return experiment


@time_machine.travel(FROZEN_NOW, tick=False)
class TestResolveExperimentVariant(ClickhouseTestMixin, BaseTest):
    def _scanner(self, experiment_id: int | None, *, variants: list[str] | None = None) -> ReplayScanner:
        config: dict = {"prompt": "p"}
        if experiment_id is None:
            scanner_type = ScannerType.MONITOR
        else:
            scanner_type = ScannerType.EXPERIMENT
            config["experiment_id"] = experiment_id
            if variants is not None:
                config["variants"] = variants
        return ReplayScanner.objects.create(
            team=self.team,
            name=f"scanner-{scanner_type}-{experiment_id}-{variants}",
            scanner_type=scanner_type,
            scanner_config=config,
            model=ScannerModel.GEMINI_3_8_FLASH,
            # The access check runs as the scan's principal; a scanner without one is refused.
            created_by=self.user,
        )

    def _inputs(
        self, scanner: ReplayScanner, session_id: str, *, backfill: ReplayScannerBackfill | None = None
    ) -> ResolveExperimentVariantInputs:
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            scanner_snapshot=snapshot_for(scanner),
            backfill=backfill,
        )
        return ResolveExperimentVariantInputs(
            observation_id=observation.id, team_id=self.team.pk, session_id=session_id
        )

    def _session(
        self,
        distinct_id: str,
        variant: str | None,
        *,
        flag_key: str = "checkout-flag",
        exposure_at: datetime = BASE_TIME,
    ) -> str:
        session_id = f"session-{distinct_id}"
        create_person(team=self.team, distinct_ids=[distinct_id])
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=BASE_TIME,
            last_timestamp=BASE_TIME + timedelta(minutes=5),
        )
        if variant is not None:
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=distinct_id,
                timestamp=exposure_at,
                properties={"$feature_flag": flag_key, "$feature_flag_response": variant},
            )
        return session_id

    def test_attributes_the_variant_and_returns_the_prompt_context(self) -> None:
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        # The description rides in the workflow history twice; only its head does.
        experiment.description = "x" * 3_000
        experiment.save()
        scanner = self._scanner(experiment.pk)
        session_id = self._session("exposed-user", "test")
        flush_persons_and_events()

        output = _resolve(self._inputs(scanner, session_id))

        assert output.applicable is True
        assert output.experiment_variant == "test"
        assert output.session_duration_s == 300.0
        assert output.experiment_context is not None
        assert output.experiment_context["feature_flag_key"] == "checkout-flag"
        assert len(output.experiment_context["description"]) == 2_000

    def test_an_unattributed_session_is_ineligible_with_not_exposed(self) -> None:
        # Both flavors of unattributed: never exposed, and exposed only outside the watched variants.
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        unexposed_session = self._session("unexposed-user", None)
        control_session = self._session("control-user", "control")
        flush_persons_and_events()

        with pytest.raises(IneligibleSessionError) as never_exposed:
            _resolve(self._inputs(self._scanner(experiment.pk), unexposed_session))
        assert never_exposed.value.kind == IneligibleSessionKind.NOT_EXPOSED

        narrowed = self._scanner(experiment.pk, variants=["test"])
        with pytest.raises(IneligibleSessionError) as outside_variants:
            _resolve(self._inputs(narrowed, control_session))
        assert outside_variants.value.kind == IneligibleSessionKind.NOT_EXPOSED

    @parameterized.expand(
        [
            # Sessions run from BASE_TIME to five minutes later.
            ("before_first_exposure", BASE_TIME + timedelta(hours=2), None),
            # Ending an experiment leaves its flag on, so a manual observe can reach a later session.
            ("after_the_experiment_ended", BASE_TIME, BASE_TIME + timedelta(minutes=2)),
        ]
    )
    def test_a_session_outside_the_experiments_run_is_not_exposed(
        self, name: str, exposure_at: datetime, end_date: datetime | None
    ) -> None:
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        if end_date is not None:
            experiment.end_date = end_date
            experiment.save()
        scanner = self._scanner(experiment.pk)
        # Distinct per case: ClickHouse rows outlive each test's transaction.
        session_id = self._session(f"outside-run-{name}", "test", exposure_at=exposure_at)
        flush_persons_and_events()

        with pytest.raises(IneligibleSessionError) as excinfo:
            _resolve(self._inputs(scanner, session_id))
        assert excinfo.value.kind == IneligibleSessionKind.NOT_EXPOSED

    @parameterized.expand(
        [
            # (scanner has a creator, backfill launcher: None = not a backfill, False = launcher gone)
            ("scanner_creator_gone", False, None, False),
            # The backfill enumerated its candidates as its launcher, so its scans authorize the same way.
            ("backfill_launcher_authorizes", False, True, True),
            # A gone launcher must not borrow the scanner creator's access the enumeration never checked.
            ("no_fallback_from_a_gone_launcher", True, False, False),
        ]
    )
    def test_a_scan_authorizes_as_the_principal_its_candidates_were_enumerated_as(
        self, name: str, scanner_creator: bool, backfill_launcher: bool | None, resolves: bool
    ) -> None:
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        if not scanner_creator:
            scanner.created_by = None
            scanner.save()
        backfill = (
            None
            if backfill_launcher is None
            else ReplayScannerBackfill.objects.for_team(self.team.pk).create(
                scanner=scanner,
                team=self.team,
                window_start=BASE_TIME - timedelta(days=1),
                window_end=BASE_TIME + timedelta(days=1),
                scanner_snapshot=snapshot_for(scanner),
                credits_per_observation=1,
                total_count=1,
                created_by=self.user if backfill_launcher else None,
            )
        )
        # Distinct per case: ClickHouse rows outlive each test's transaction.
        session_id = self._session(f"principal-{name}", "test")
        flush_persons_and_events()

        if resolves:
            assert _resolve(self._inputs(scanner, session_id, backfill=backfill)).experiment_variant == "test"
        else:
            with pytest.raises(IneligibleSessionError) as excinfo:
                _resolve(self._inputs(scanner, session_id, backfill=backfill))
            assert excinfo.value.kind == IneligibleSessionKind.EXPERIMENT_UNRESOLVED

    @parameterized.expand(
        [
            ("exposures_still_computing", "EXPOSURES_STILL_COMPUTING_MESSAGE"),
            ("cohort_calculating", "COHORT_NOT_CALCULATED_MESSAGE"),
        ]
    )
    def test_a_transient_linkage_state_is_retryable_not_terminal(self, name: str, message_name: str) -> None:
        # Both finish on their own, and the unique (scanner, session) row means a session failed for
        # good is never picked up again.
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from products.experiments.backend.facade import replay as experiments_replay

        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        session_id = self._session(f"transient-{name}", "test")
        flush_persons_and_events()

        with (
            patch(
                "products.experiments.backend.facade.replay.resolve_exposure_linkage",
                side_effect=DRFValidationError(getattr(experiments_replay, message_name)),
            ),
            pytest.raises(ScannerFailureError) as excinfo,
        ):
            _resolve(self._inputs(scanner, session_id))
        assert excinfo.value.kind == FailureKind.INFRA_TRANSIENT

    def test_a_deleted_experiment_is_ineligible_with_experiment_unresolved(self) -> None:
        # Its own distinct id: ClickHouse rows outlive each test's transaction, so reusing another
        # test's id on the shared team would double-map the person.
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        session_id = self._session("deleted-exp-user", "test")
        flush_persons_and_events()
        experiment.deleted = True
        experiment.save()

        with pytest.raises(IneligibleSessionError) as excinfo:
            _resolve(self._inputs(scanner, session_id))
        assert excinfo.value.kind == IneligibleSessionKind.EXPERIMENT_UNRESOLVED

    def test_a_scanner_without_an_experiment_is_not_applicable(self) -> None:
        scanner = self._scanner(None)
        session_id = self._session("plain-user", None)
        flush_persons_and_events()

        output = _resolve(self._inputs(scanner, session_id))

        assert output.applicable is False
        assert output.experiment_variant is None
