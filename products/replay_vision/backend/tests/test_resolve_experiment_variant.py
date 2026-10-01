from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.persons import create_person

from products.replay_vision.backend.error_kinds import IneligibleSessionKind
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
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

    def _inputs(self, scanner: ReplayScanner, session_id: str) -> ResolveExperimentVariantInputs:
        observation = ReplayObservation.objects.create(
            scanner=scanner, team=self.team, session_id=session_id, scanner_snapshot=snapshot_for(scanner)
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

    def test_a_session_that_predates_the_exposure_is_not_exposed(self) -> None:
        # The bound the recordings list enforces: a manual observe on a session recorded before the
        # person's first exposure must be refused, not attributed.
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        session_id = self._session("late-exposed-user", "test", exposure_at=BASE_TIME + timedelta(hours=2))
        flush_persons_and_events()

        with pytest.raises(IneligibleSessionError) as excinfo:
            _resolve(self._inputs(scanner, session_id))
        assert excinfo.value.kind == IneligibleSessionKind.NOT_EXPOSED

    def test_a_scan_without_a_principal_is_unresolved(self) -> None:
        # The access check refuses userless callers, same as every other exposure read; a scanner
        # whose creator was deleted has no principal to authorize as.
        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        scanner.created_by = None
        scanner.save()
        session_id = self._session("no-principal-user", "test")
        flush_persons_and_events()

        with pytest.raises(IneligibleSessionError) as excinfo:
            _resolve(self._inputs(scanner, session_id))
        assert excinfo.value.kind == IneligibleSessionKind.EXPERIMENT_UNRESOLVED

    def test_exposures_still_computing_is_retryable_not_terminal(self) -> None:
        # The precomputation finishes on its own; failing the session for good would drop it.
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from products.experiments.backend.facade.replay import EXPOSURES_STILL_COMPUTING_MESSAGE

        experiment = _launched_experiment(self, "checkout-flag", ["control", "test"])
        scanner = self._scanner(experiment.pk)
        session_id = self._session("computing-user", "test")
        flush_persons_and_events()

        with (
            patch(
                "products.experiments.backend.facade.replay.resolve_exposure_linkage",
                side_effect=DRFValidationError(EXPOSURES_STILL_COMPUTING_MESSAGE),
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
