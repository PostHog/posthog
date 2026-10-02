from datetime import timedelta
from typing import Any

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.experiment_variants import UNATTRIBUTED_VARIANT
from products.replay_vision.backend.models.experiment_synthesis import ExperimentSynthesis, ExperimentSynthesisStatus
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_UNSET = object()


class TestExperimentVariants(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.experiment = create_experiment(
            self.team, "checkout-flag", launched=True, variants=["control", "test", "beta"]
        )
        self.scanner = self._create_scanner(
            name="experiment-scanner",
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "p", "experiment_id": self.experiment.id},
        )
        self.variants_url = f"{self.scanners_url}{self.scanner.id}/variants/"
        self._minutes_ago = 100

    def _observation(
        self,
        variant: Any = _UNSET,
        *,
        distinct_id: str = "person-a",
        duration_s: float = 60,
        status: str = ObservationStatus.SUCCEEDED,
        rates: dict[str, float] | None = None,
    ) -> ReplayObservation:
        result: dict[str, Any] = {"model_output": {"title": "t", "summary": "s"}, "session_duration_s": duration_s}
        if variant is not _UNSET:
            result["experiment_variant"] = variant
        snapshot = {**snapshot_for(self.scanner), "variant_sampling_rates": rates}
        # Each call lands later than the last, so "newest first" has a defined order.
        self._minutes_ago -= 1
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"sess-{self._minutes_ago}",
            distinct_id=distinct_id,
            status=status,
            completed_at=timezone.now() - timedelta(minutes=self._minutes_ago),
            scanner_snapshot=snapshot,
            scanner_result=result if status == ObservationStatus.SUCCEEDED else {},
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def test_readout_counts_each_variant_from_its_observations(self) -> None:
        rates = {"control": 0.1, "test": 0.9, "beta": 0.5}
        self._observation("control", distinct_id="a", duration_s=100, rates=rates)
        second = self._observation("control", distinct_id="a", duration_s=200, rates=rates)
        newest = self._observation("control", distinct_id="c", duration_s=600, rates=rates)
        # Without balancing the variant shared the scanner-wide rate the snapshot recorded.
        self._observation("test", distinct_id="b", duration_s=50, rates=None)
        self._observation(_UNSET)
        self._observation(None)
        # Only succeeded scans count.
        self._observation("control", distinct_id="z", status=ObservationStatus.FAILED)

        resp = self.client.get(self.variants_url)

        assert resp.status_code == 200, resp.json()
        body = resp.json()
        by_key = {v["key"]: v for v in body["variants"]}
        # Watched variants in the experiment's order, a variant with no scans included.
        assert [v["key"] for v in body["variants"]] == ["control", "test", "beta"]
        assert by_key["control"]["observations"] == 3
        assert by_key["control"]["distinct_people"] == 2
        assert by_key["control"]["median_session_duration_s"] == 200
        assert by_key["control"]["sampling_rate"] == 0.1
        assert [o["id"] for o in by_key["control"]["latest_observations"]] == [str(newest.id), str(second.id)]
        assert by_key["test"]["observations"] == 1
        assert by_key["test"]["sampling_rate"] == self.scanner.sampling_rate
        assert by_key["beta"] == {**by_key["beta"], "observations": 0, "sampling_rate": None, "latest_observations": []}
        # A missing key and a JSON null both mean unattributed.
        assert body["unattributed_count"] == 2
        assert body["window"]["total_observations"] == 6
        assert body["experiment"]["id"] == self.experiment.id
        assert body["experiment"]["current_day"] >= 1
        assert body["differences"] is None and body["synthesis"] is None
        assert all(v["digest"] is None for v in body["variants"])

    def test_readout_shows_the_current_versions_synthesis(self) -> None:
        # A prompt edit bumps the version; an older version's synthesis summarized differently focused
        # summaries, so it must not describe the current ones.
        def synthesis(version: int, status: str, digest_statement: str) -> ExperimentSynthesis:
            return ExperimentSynthesis.objects.for_team(self.team.id).create(
                scanner=self.scanner,
                scanner_version=version,
                status=status,
                computed_at=timezone.now() if status != ExperimentSynthesisStatus.RUNNING else None,
                digests={"control": [{"theme_key": "hesitate", "statement": digest_statement, "count": 4}]},
                differences=[{"statement": "diff", "theme_key": "hesitate", "counts": {"control": 4, "test": 1}}],
            )

        synthesis(self.scanner.scanner_version - 1 or 1, ExperimentSynthesisStatus.SUCCEEDED, "old version")
        self.scanner.scanner_config = {**self.scanner.scanner_config, "prompt": "sharper"}
        self.scanner.save()
        self.scanner.refresh_from_db()
        synthesis(self.scanner.scanner_version, ExperimentSynthesisStatus.SUCCEEDED, "current version")
        synthesis(self.scanner.scanner_version, ExperimentSynthesisStatus.RUNNING, "in flight")

        body = self.client.get(self.variants_url).json()

        control = next(v for v in body["variants"] if v["key"] == "control")
        assert [line["statement"] for line in control["digest"]] == ["current version"]
        assert body["differences"] == [
            {"statement": "diff", "theme_key": "hesitate", "counts": {"control": 4, "test": 1}}
        ]
        # The state reports the newest run, even while the prose still comes from the last finished one.
        assert body["synthesis"]["status"] == ExperimentSynthesisStatus.RUNNING
        # A variant the synthesis said nothing about gets an empty digest, not a missing one.
        assert next(v for v in body["variants"] if v["key"] == "test")["digest"] == []

    def test_a_non_experiment_scanner_has_no_variants(self) -> None:
        monitor = self._create_scanner(name="monitor")
        resp = self.client.get(f"{self.scanners_url}{monitor.id}/variants/")
        assert resp.status_code == 400

    @parameterized.expand(
        [
            ("named", "test", {"test"}),
            ("unattributed", UNATTRIBUTED_VARIANT, {"missing", "null"}),
            ("both", f"control,{UNATTRIBUTED_VARIANT}", {"control", "missing", "null"}),
        ]
    )
    def test_observations_filter_by_variant(self, _name: str, value: str, expected: set[str]) -> None:
        observations = {
            "control": self._observation("control"),
            "test": self._observation("test"),
            "missing": self._observation(_UNSET),
            "null": self._observation(None),
        }

        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?variant={value}")

        assert resp.status_code == 200, resp.json()
        returned = {o["id"] for o in resp.json()["results"]}
        assert returned == {str(observations[name].id) for name in expected}
