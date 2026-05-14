from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_lens import LensModel, LensProvider, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)


class _VisionAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    @property
    def lenses_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/lenses/"

    def observations_url(self, lens_id: str) -> str:
        return f"/api/environments/{self.team.id}/vision/lenses/{lens_id}/observations/"

    def _create_lens(self, **overrides) -> ReplayLens:
        defaults = {
            "team": self.team,
            "name": "my-lens",
            "lens_type": LensType.MONITOR,
            "lens_config": {"prompt": "did the user check out?"},
            "model": LensModel.GEMINI_3_FLASH,
        }
        defaults.update(overrides)
        return ReplayLens.objects.create(**defaults)


class TestReplayLensViewSet(_VisionAPITestCase):
    def test_create_minimal(self) -> None:
        resp = self.client.post(
            self.lenses_url,
            data={
                "name": "checkout-monitor",
                "lens_type": LensType.MONITOR,
                "lens_config": {"prompt": "did checkout complete?"},
                "model": LensModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body = resp.json()
        self.assertEqual(body["name"], "checkout-monitor")
        self.assertTrue(body["enabled"])
        self.assertEqual(body["sampling_rate"], 1.0)
        self.assertEqual(body["lens_version"], 1)
        self.assertEqual(body["created_by"]["id"], self.user.id)

    @parameterized.expand(["name", "lens_type", "lens_config", "model"])
    def test_create_validates_required_field(self, missing_field: str) -> None:
        payload = {
            "name": f"missing-{missing_field}",
            "lens_type": LensType.MONITOR,
            "lens_config": {"prompt": "p"},
            "model": LensModel.GEMINI_3_FLASH,
        }
        del payload[missing_field]
        resp = self.client.post(self.lenses_url, data=payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], missing_field)

    def test_create_round_trips_provider(self) -> None:
        resp = self.client.post(
            self.lenses_url,
            data={
                "name": "explicit-provider",
                "lens_type": LensType.MONITOR,
                "lens_config": {"prompt": "p"},
                "model": LensModel.GEMINI_3_FLASH,
                "provider": LensProvider.GOOGLE,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["provider"], LensProvider.GOOGLE)

    @parameterized.expand([("below", -0.1), ("above", 1.5)])
    def test_create_rejects_out_of_range_sampling_rate(self, _label: str, value: float) -> None:
        resp = self.client.post(
            self.lenses_url,
            data={
                "name": f"rate-{value}",
                "lens_type": LensType.MONITOR,
                "lens_config": {"prompt": "p"},
                "model": LensModel.GEMINI_3_FLASH,
                "sampling_rate": value,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "sampling_rate")

    def test_create_duplicate_name_rejected(self) -> None:
        self._create_lens(name="dup")
        resp = self.client.post(
            self.lenses_url,
            data={
                "name": "dup",
                "lens_type": LensType.MONITOR,
                "lens_config": {"prompt": "p"},
                "model": LensModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_only_team_lenses(self) -> None:
        self._create_lens(name="ours")
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        ReplayLens.objects.create(
            team=other_team,
            name="theirs",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "p"},
            model=LensModel.GEMINI_3_FLASH,
        )
        resp = self.client.get(self.lenses_url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["ours"])

    def test_retrieve(self) -> None:
        lens = self._create_lens()
        resp = self.client.get(f"{self.lenses_url}{lens.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], str(lens.id))

    def test_patch_bumps_lens_version_on_tracked_change(self) -> None:
        lens = self._create_lens()
        resp = self.client.patch(
            f"{self.lenses_url}{lens.id}/",
            data={"sampling_rate": 0.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["lens_version"], 2)
        self.assertEqual(resp.json()["sampling_rate"], 0.5)

    def test_patch_does_not_bump_on_metadata_change(self) -> None:
        lens = self._create_lens()
        resp = self.client.patch(
            f"{self.lenses_url}{lens.id}/",
            data={"description": "now described"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["lens_version"], 1)

    def test_delete(self) -> None:
        lens = self._create_lens()
        resp = self.client.delete(f"{self.lenses_url}{lens.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ReplayLens.objects.filter(id=lens.id).exists())

    @parameterized.expand(
        [
            ("enabled", "false", 1),
            ("lens_type", LensType.CLASSIFIER, 1),
            ("emits_signals", "true", 1),
        ]
    )
    def test_filterset(self, field: str, value: str, expected_count: int) -> None:
        if field == "enabled":
            self._create_lens(name="enabled-lens")
            self._create_lens(name="disabled-lens", enabled=False)
        elif field == "lens_type":
            self._create_lens(name="monitor-lens")
            self._create_lens(name="classifier-lens", lens_type=LensType.CLASSIFIER)
        elif field == "emits_signals":
            self._create_lens(name="silent")
            self._create_lens(name="loud", emits_signals=True)
        resp = self.client.get(f"{self.lenses_url}?{field}={value}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), expected_count)

    def test_order_by_descending(self) -> None:
        self._create_lens(name="a-lens")
        self._create_lens(name="b-lens")
        resp = self.client.get(f"{self.lenses_url}?order_by=-name")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["b-lens", "a-lens"])


class TestReplayLensViewSetFeatureFlag(APIBaseTest):
    @property
    def lenses_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/lenses/"

    @patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_returns_404_on_list(self, _flag_mock) -> None:
        resp = self.client.get(self.lenses_url)
        self.assertEqual(resp.status_code, 404)

    @patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_returns_404_on_create(self, _flag_mock) -> None:
        resp = self.client.post(self.lenses_url, data={"name": "x"}, format="json")
        self.assertEqual(resp.status_code, 404)


class TestReplayObservationViewSet(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lens = self._create_lens()

    def _create_observation(self, **overrides) -> ReplayObservation:
        defaults = {
            "lens": self.lens,
            "session_id": "sess-1",
            "lens_version": self.lens.lens_version,
            "lens_config_snapshot": self.lens.lens_config,
            "triggered_by": ObservationTrigger.SCHEDULE,
        }
        defaults.update(overrides)
        return ReplayObservation.objects.create(**defaults)

    def test_list_observations_for_lens(self) -> None:
        self._create_observation(session_id="s1")
        self._create_observation(session_id="s2")
        resp = self.client.get(self.observations_url(str(self.lens.id)))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 2)

    def test_malformed_lens_id_returns_404(self) -> None:
        resp = self.client.get(self.observations_url("not-a-uuid"))
        self.assertEqual(resp.status_code, 404)

    def test_unknown_lens_id_returns_404(self) -> None:
        import uuid as _uuid

        resp = self.client.get(self.observations_url(str(_uuid.uuid4())))
        self.assertEqual(resp.status_code, 404)

    def test_other_team_lens_id_returns_404(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_lens = ReplayLens.objects.create(
            team=other_team,
            name="theirs",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "p"},
            model=LensModel.GEMINI_3_FLASH,
        )
        resp = self.client.get(self.observations_url(str(other_lens.id)))
        self.assertEqual(resp.status_code, 404)

    def test_list_excludes_observations_from_other_lens(self) -> None:
        other_lens = self._create_lens(name="other-lens")
        self._create_observation(session_id="ours")
        ReplayObservation.objects.create(
            lens=other_lens,
            session_id="theirs",
            lens_version=other_lens.lens_version,
            lens_config_snapshot=other_lens.lens_config,
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        resp = self.client.get(self.observations_url(str(self.lens.id)))
        sessions = [r["session_id"] for r in resp.json()["results"]]
        self.assertEqual(sessions, ["ours"])

    def test_retrieve_observation(self) -> None:
        obs = self._create_observation()
        resp = self.client.get(f"{self.observations_url(str(self.lens.id))}{obs.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["session_id"], obs.session_id)

    @parameterized.expand(
        [
            ("status", ObservationStatus.FAILED, 1),
            ("triggered_by", ObservationTrigger.ON_DEMAND, 1),
            ("session_id", "needle", 1),
        ]
    )
    def test_filterset(self, field: str, value: str, expected_count: int) -> None:
        if field == "status":
            self._create_observation(session_id="ok")
            self._create_observation(
                session_id="bad",
                status=ObservationStatus.FAILED,
                error_reason="oops",
                completed_at=timezone.now(),
            )
        elif field == "triggered_by":
            self._create_observation(session_id="auto")
            self._create_observation(session_id="manual", triggered_by=ObservationTrigger.ON_DEMAND)
        elif field == "session_id":
            self._create_observation(session_id="needle")
            self._create_observation(session_id="haystack")
        resp = self.client.get(f"{self.observations_url(str(self.lens.id))}?{field}={value}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), expected_count)

    def test_order_by_created_at_descending(self) -> None:
        first = self._create_observation(session_id="first")
        second = self._create_observation(session_id="second")
        resp = self.client.get(f"{self.observations_url(str(self.lens.id))}?order_by=-created_at")
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertEqual(ids, [str(second.id), str(first.id)])

    def test_pagination(self) -> None:
        for i in range(3):
            self._create_observation(session_id=f"s{i}")
        resp = self.client.get(f"{self.observations_url(str(self.lens.id))}?limit=2")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["results"]), 2)
        self.assertIsNotNone(body.get("next"))
