import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.replay_vision.backend import variant_synthesis
from products.replay_vision.backend.embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT
from products.replay_vision.backend.models.replay_experiment_synthesis import ReplayExperimentSynthesis, ReplayExperimentSynthesisStatus
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for

_MODULE = "products.replay_vision.backend.variant_synthesis"


class _SynthesisTestBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        experiment = create_experiment(self.team, "checkout-flag", launched=True, variants=["control", "test"])
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="experiment-scanner",
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "p", "experiment_id": experiment.id},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self._count = 0

    def _summaries(self, variant: str, n: int, *, text: str = "User browsed") -> list[ReplayObservation]:
        rows = []
        for _ in range(n):
            self._count += 1
            rows.append(
                ReplayObservation.objects.create(
                    scanner=self.scanner,
                    team=self.team,
                    session_id=f"sess-{self._count}",
                    status=ObservationStatus.SUCCEEDED,
                    completed_at=timezone.now() - timedelta(minutes=self._count),
                    scanner_snapshot=snapshot_for(self.scanner),
                    scanner_result={
                        "model_output": {"title": f"{text} {self._count}", "summary": "s"},
                        "experiment_variant": variant,
                    },
                    triggered_by=ObservationTrigger.SCHEDULE,
                )
            )
        return rows

    def _run(self, **overrides: Any) -> ReplayExperimentSynthesis:
        defaults: dict[str, Any] = {"scanner": self.scanner, "scanner_version": self.scanner.scanner_version}
        defaults.update(overrides)
        return ReplayExperimentSynthesis.objects.for_team(self.team.id).create(**defaults)


class TestClaimDueRefresh(_SynthesisTestBase):
    @parameterized.expand(
        [
            # (summaries now, last succeeded run's count or None, expected due)
            ("first_run_once_enough", 10, None, True),
            ("first_run_waits_for_enough", 9, None, False),
            ("fifty_new_is_due_on_a_large_set", 1050, 1000, True),
            ("ten_percent_short_of_fifty_is_not", 1049, 1000, False),
            ("ten_percent_growth_is_due", 110, 100, True),
            ("growth_below_the_floor_is_not", 19, 10, False),
            ("growth_at_the_floor_is_due", 20, 10, True),
        ]
    )
    def test_refresh_is_due_on_enough_new_summaries(
        self, _name: str, now: int, considered: int | None, expected: bool
    ) -> None:
        if considered is not None:
            self._run(
                status=ReplayExperimentSynthesisStatus.SUCCEEDED,
                computed_at=timezone.now() - timedelta(hours=2),
                observations_considered={"control": considered},
            )
        with patch(f"{_MODULE}.synthesis_observations") as observations:
            observations.return_value.count.return_value = now
            claimed = variant_synthesis.claim_due_refresh(self.scanner)

        assert (claimed is not None) is expected
        if expected:
            assert claimed is not None and claimed.status == ReplayExperimentSynthesisStatus.RUNNING

    @parameterized.expand(
        [
            ("a_run_in_flight", {"status": ReplayExperimentSynthesisStatus.RUNNING}),
            (
                "a_recent_failure",
                {"status": ReplayExperimentSynthesisStatus.FAILED, "computed_at": timezone.now()},
            ),
            (
                "a_recent_success",
                {
                    "status": ReplayExperimentSynthesisStatus.SUCCEEDED,
                    "computed_at": timezone.now(),
                    "observations_considered": {"control": 10},
                },
            ),
        ]
    )
    def test_refresh_holds_back(self, _name: str, latest: dict[str, Any]) -> None:
        # Each of these bounds what an absorbed-cost refresh can spend: no second run in flight, no
        # retry storm after a failure, no rerun within the cooldown.
        self._run(**latest)
        with patch(f"{_MODULE}.synthesis_observations") as observations:
            observations.return_value.count.return_value = 10_000
            assert variant_synthesis.claim_due_refresh(self.scanner) is None

    def test_a_stale_running_row_stops_blocking(self) -> None:
        # A workflow that died without failing its row would otherwise hold the slot forever.
        stale = self._run()
        ReplayExperimentSynthesis.objects.for_team(self.team.id).filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )

        synthesis, created = variant_synthesis.start_synthesis_run(self.scanner, user=self.user)

        assert created and synthesis.pk != stale.pk
        stale.refresh_from_db()
        assert stale.status == ReplayExperimentSynthesisStatus.FAILED

    def test_starting_while_one_runs_returns_that_run(self) -> None:
        running = self._run()
        synthesis, created = variant_synthesis.start_synthesis_run(self.scanner, user=self.user)
        assert not created and synthesis.pk == running.pk


class TestSynthesisSteps(_SynthesisTestBase):
    def _distances(self, rows_by_theme: dict[str, dict[ReplayObservation, float]]) -> Any:
        by_vector = {key: {str(obs.id): d for obs, d in rows.items()} for key, rows in rows_by_theme.items()}

        def query_vector(_team: Any, description: str) -> list[float]:
            return [float(list(by_vector).index(description))]

        def theme_distances(_team: Any, _scanner_id: Any, vector: list[float], *, since: Any) -> dict[str, float]:
            return by_vector[list(by_vector)[int(vector[0])]]

        return query_vector, theme_distances

    def test_a_run_counts_from_embeddings_and_never_from_the_model(self) -> None:
        control = self._summaries("control", 6)
        test = self._summaries("test", 6)
        synthesis = self._run()
        responses = iter(
            [
                variant_synthesis._ProposedThemes(
                    themes=[
                        variant_synthesis._ProposedTheme(key="Hesitates at checkout", description="hesitate"),
                        variant_synthesis._ProposedTheme(key="opens_help", description="help"),
                    ]
                ),
                variant_synthesis._Differences(
                    differences=[
                        variant_synthesis._Difference(theme_key="opens_help", statement="Test opens help more."),
                        # A theme the run never assigned must not reach the readout.
                        variant_synthesis._Difference(theme_key="invented", statement="Made up."),
                    ]
                ),
            ]
        )
        captured: list[str] = []

        digests = {
            "control": variant_synthesis._Digest(
                lines=[variant_synthesis._DigestLine(theme_key="hesitates_at_checkout", statement="Control waits.")]
            ),
            "test": variant_synthesis._Digest(
                lines=[variant_synthesis._DigestLine(theme_key="opens_help", statement="Test asks for help.")]
            ),
        }

        def generate(model: Any, _system: str, contents: str, **_kw: Any) -> Any:
            captured.append(contents)
            if model is variant_synthesis._Digest:
                return next(digest for group, digest in digests.items() if f"Group: {group}" in contents)
            return next(responses)

        # Embeddings put 4 control and 1 test summary near "hesitate", 1 control and 5 test near "help",
        # and one control summary has no embedding yet, so it stays out of the denominator.
        far = variant_synthesis.THEME_MATCH_MAX_DISTANCE + 0.2
        query_vector, theme_distances = self._distances(
            {
                "hesitate": {
                    **dict.fromkeys(control[:4], 0.1),
                    control[4]: far,
                    test[0]: 0.2,
                    **dict.fromkeys(test[1:], far),
                },
                "help": {
                    **dict.fromkeys(control[:4], far),
                    control[4]: 0.3,
                    **dict.fromkeys(test[1:], 0.1),
                    test[0]: far,
                },
            }
        )
        with (
            patch(f"{_MODULE}._generate", side_effect=generate),
            patch(f"{_MODULE}.query_vector_for", side_effect=query_vector),
            patch(f"{_MODULE}._theme_distances", side_effect=theme_distances),
        ):
            for step in ("propose_themes", "assign_themes", "write_digests", "write_differences"):
                getattr(variant_synthesis, step)(synthesis.id, self.team.id)

        synthesis.refresh_from_db()
        assert synthesis.status == ReplayExperimentSynthesisStatus.SUCCEEDED
        assert synthesis.observations_considered == {"control": 5, "test": 6}
        themes = {theme["key"]: theme for theme in synthesis.themes}
        assert themes["hesitates_at_checkout"]["counts_by_variant"] == {"control": 4, "test": 1}
        assert themes["opens_help"]["counts_by_variant"] == {"control": 1, "test": 5}
        assert synthesis.digests["control"][0] == {
            "theme_key": "hesitates_at_checkout",
            "statement": "Control waits.",
            "count": 4,
        }
        assert synthesis.differences == [
            {"statement": "Test opens help more.", "theme_key": "opens_help", "counts": {"control": 1, "test": 5}}
        ]
        # The theme proposal never sees which group a summary came from.
        assert "control" not in captured[0] and "test" not in captured[0].replace("A/B test", "")

    def test_a_withdrawn_consent_stops_the_run(self) -> None:
        self._summaries("control", 10)
        synthesis = self._run()
        with (
            patch(f"{_MODULE}.is_ai_data_processing_approved", return_value=False),
            pytest.raises(variant_synthesis.SynthesisError),
        ):
            variant_synthesis.propose_themes(synthesis.id, self.team.id)


class TestThemeDistancesAgainstClickHouse(ClickhouseTestMixin, APIBaseTest):
    def test_reads_each_observations_closest_rendering_within_the_scanner(self) -> None:
        # The match runs on the embeddings semantic search stores, so the scope and the min over
        # renderings must hold against the real table, not a mock.
        scanner_id = uuid.uuid4()
        near, far, other_scanner = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        now = timezone.now()

        def vector(x: float, y: float) -> list[float]:
            return [x, y, *([0.0] * 3070)]

        def row(document_id: str, embedding: list[float], scanner: uuid.UUID, rendering: str = "summary") -> tuple:
            return (
                self.team.pk,
                EMBEDDING_PRODUCT,
                EMBEDDING_DOCUMENT_TYPE,
                rendering,
                document_id,
                now,
                now,
                "content",
                json.dumps({"scanner_id": str(scanner)}),
                embedding,
                now,
                0,
                0,
            )

        sync_execute(
            """
            INSERT INTO distributed_posthog_document_embeddings_text_embedding_3_large_3072 (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                row(near, vector(1, 0), scanner_id),
                # A second, worse rendering of the same observation must not win.
                row(near, vector(0, 1), scanner_id, rendering="title"),
                row(far, vector(0, 1), scanner_id),
                row(other_scanner, vector(1, 0), uuid.uuid4()),
            ],
            flush=False,
            team_id=self.team.pk,
        )

        distances = variant_synthesis._theme_distances(
            self.team, scanner_id, vector(1, 0), since=now - timedelta(hours=1)
        )

        assert set(distances) == {near, far}
        assert distances[near] == pytest.approx(0.0, abs=1e-6)
        assert distances[far] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_step", [None, "assign"])
async def test_workflow_runs_each_step_and_fails_the_row_on_error(failing_step: str | None) -> None:
    # A failed step must still finish the row, or the one-running constraint blocks every later run.
    from products.replay_vision.backend.temporal.activities.experiment_synthesis import (
        assign_synthesis_themes_activity,
        fail_experiment_synthesis_activity,
        propose_synthesis_themes_activity,
        write_synthesis_differences_activity,
        write_synthesis_digests_activity,
    )
    from products.replay_vision.backend.temporal.experiment_synthesis_workflow import ExperimentSynthesisWorkflow
    from products.replay_vision.backend.temporal.synthesis_types import ExperimentSynthesisInputs

    calls: list[Any] = []

    async def execute_activity(activity_fn: Any, activity_input: Any, **_kw: Any) -> None:
        calls.append(activity_fn)
        if failing_step == "assign" and activity_fn is assign_synthesis_themes_activity:
            raise RuntimeError("no embeddings")

    inputs = ExperimentSynthesisInputs(synthesis_id=uuid.uuid4(), team_id=1)
    with patch("temporalio.workflow.execute_activity", side_effect=execute_activity):
        if failing_step is None:
            await ExperimentSynthesisWorkflow().run(inputs)
        else:
            with pytest.raises(RuntimeError):
                await ExperimentSynthesisWorkflow().run(inputs)

    if failing_step is None:
        assert calls == [
            propose_synthesis_themes_activity,
            assign_synthesis_themes_activity,
            write_synthesis_digests_activity,
            write_synthesis_differences_activity,
        ]
    else:
        assert calls == [
            propose_synthesis_themes_activity,
            assign_synthesis_themes_activity,
            fail_experiment_synthesis_activity,
        ]
