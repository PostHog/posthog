import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.experiment_variants import UNATTRIBUTED_VARIANT
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.signals.backend.facade.api import ScoutStructuredRecord, SourceScout

_UNSET = object()
_SIGNALS = "products.replay_vision.backend.variant_analysis.signals_facade"
_RECORDED_AT = datetime(2026, 9, 1, tzinfo=UTC)


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
        assert body["analysis"] is None and body["differences"] is None

    @parameterized.expand([("current_version", True), ("older_version", False)])
    def test_readout_shows_the_variant_analysis_for_the_current_version(self, _name: str, current: bool) -> None:
        control = self._observation("control")
        test = self._observation("test")
        payload = {
            # A prompt edit bumps the version, and a record from before it compared differently focused summaries.
            "scanner_version": self.scanner.scanner_version if current else self.scanner.scanner_version - 1,
            "observations_read": {"control": 30, "test": 28},
            "variants": {
                # The scout cites ids itself, so one from another variant or one that isn't an observation of
                # this scanner must not be shown as evidence.
                "control": [
                    {
                        "theme": "Hesitates at checkout",
                        "statement": "Waits on the payment step.",
                        "count": 9,
                        "example_observation_ids": [str(control.id), str(test.id)],
                    }
                ],
                "test": [
                    {
                        "theme": "Hesitates at checkout",
                        "statement": "Rarely waits.",
                        "count": 2,
                        "example_observation_ids": [str(uuid.uuid4()), "not-an-id"],
                    }
                ],
            },
            "differences": [
                {
                    "theme": "Hesitates at checkout",
                    "statement": "Control waits more.",
                    "counts": {"control": 9, "test": 2},
                }
            ],
        }
        scout = SourceScout(config_id="config-1", skill_name="signals-scout-x", enabled=True, created_at=_RECORDED_AT)
        record = ScoutStructuredRecord(
            payload=payload, recorded_at=_RECORDED_AT, skill_name="signals-scout-x", run_id="r"
        )

        with (
            patch(f"{_SIGNALS}.scouts_for_source", return_value=[scout]),
            patch(f"{_SIGNALS}.latest_structured_output_for_source", return_value=record),
        ):
            body = self.client.get(self.variants_url).json()

        by_key = {v["key"]: v for v in body["variants"]}
        assert body["analysis"]["scout_config_id"] == "config-1"
        assert body["analysis"]["current"] is current
        if not current:
            assert body["differences"] is None
            assert all(v["digest"] is None and v["analysis_observations"] is None for v in body["variants"])
            return
        assert by_key["control"]["digest"] == [
            {
                "theme": "Hesitates at checkout",
                "statement": "Waits on the payment step.",
                "count": 9,
                "example_observation_ids": [str(control.id)],
            }
        ]
        assert by_key["test"]["digest"][0]["example_observation_ids"] == []
        assert by_key["control"]["analysis_observations"] == 30
        assert by_key["beta"]["digest"] == [] and by_key["beta"]["analysis_observations"] == 0
        assert body["differences"] == payload["differences"]

    def test_a_child_scoped_api_key_cannot_read_the_parent_teams_analysis(self) -> None:
        # The variant analysis is read from the scout's records on the parent team, so a key
        # scoped only to a child environment must not read it through the child's scanner.
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.team import Team
        from posthog.models.utils import generate_random_token_personal, hash_key_value

        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        experiment = create_experiment(env, "env-flag", launched=True, variants=["control", "test"])
        scanner = self._create_scanner(
            name="child-experiment-scanner",
            team=env,
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "p", "experiment_id": experiment.id},
        )
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["replay_scanner:read", "session_recording:read"],
            scoped_teams=[env.id],
        )
        self.client.logout()

        with patch(f"{_SIGNALS}.latest_structured_output_for_source") as read_analysis:
            response = self.client.get(
                f"/api/projects/{env.id}/vision/scanners/{scanner.id}/variants/",
                HTTP_AUTHORIZATION=f"Bearer {raw}",
            )

        assert response.status_code == 403, response.content
        assert not read_analysis.called

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
