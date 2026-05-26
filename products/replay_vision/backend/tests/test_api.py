from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Organization, Team
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


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
    def scanners_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/"

    def observations_url(self, scanner_id: str) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/{scanner_id}/observations/"

    def _create_scanner(self, **overrides) -> ReplayScanner:
        defaults = {
            "team": self.team,
            "name": "my-scanner",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "did the user check out?"},
            "model": ScannerModel.GEMINI_3_FLASH,
        }
        defaults.update(overrides)
        return ReplayScanner.objects.create(**defaults)


class TestReplayScannerViewSet(_VisionAPITestCase):
    def test_create_minimal(self) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "checkout-monitor",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "did checkout complete?"},
                "model": ScannerModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body = resp.json()
        self.assertEqual(body["name"], "checkout-monitor")
        self.assertTrue(body["enabled"])
        self.assertEqual(body["sampling_rate"], 1.0)
        self.assertEqual(body["scanner_version"], 1)
        self.assertEqual(body["created_by"]["id"], self.user.id)

    @parameterized.expand(["name", "scanner_type", "scanner_config", "model"])
    def test_create_validates_required_field(self, missing_field: str) -> None:
        payload = {
            "name": f"missing-{missing_field}",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "p"},
            "model": ScannerModel.GEMINI_3_FLASH,
        }
        del payload[missing_field]
        resp = self.client.post(self.scanners_url, data=payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], missing_field)

    def test_create_round_trips_provider(self) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "explicit-provider",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "provider": ScannerProvider.GOOGLE,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["provider"], ScannerProvider.GOOGLE)

    @parameterized.expand([("below", -0.1), ("above", 1.5)])
    def test_create_rejects_out_of_range_sampling_rate(self, _label: str, value: float) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": f"rate-{value}",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "sampling_rate": value,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "sampling_rate")

    def test_create_duplicate_name_rejected(self) -> None:
        self._create_scanner(name="dup")
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "dup",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_only_team_scanners(self) -> None:
        self._create_scanner(name="ours")
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        resp = self.client.get(self.scanners_url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["ours"])

    def test_retrieve(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], str(scanner.id))

    def test_patch_bumps_scanner_version_on_tracked_change(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"sampling_rate": 0.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["scanner_version"], 2)
        self.assertEqual(resp.json()["sampling_rate"], 0.5)

    def test_patch_does_not_bump_on_metadata_change(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"description": "now described"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scanner_version"], 1)

    @parameterized.expand(
        [
            ("monitor", ScannerType.MONITOR, {"prompt": "p"}),
            ("classifier", ScannerType.CLASSIFIER, {"prompt": "p", "tags": ["a", "b"]}),
            ("scorer", ScannerType.SCORER, {"prompt": "p", "scale": {"min": 0, "max": 10}}),
            ("summarizer", ScannerType.SUMMARIZER, {"prompt": "p"}),
            ("indexer", ScannerType.INDEXER, {}),
        ]
    )
    def test_create_accepts_valid_scanner_config_per_type(
        self, label: str, scanner_type: ScannerType, scanner_config: dict
    ) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": f"valid-{label}",
                "scanner_type": scanner_type,
                "scanner_config": scanner_config,
                "model": ScannerModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())

    @parameterized.expand(
        [
            ("classifier_without_tags", ScannerType.CLASSIFIER, {"prompt": "p"}),
            ("classifier_empty_tags", ScannerType.CLASSIFIER, {"prompt": "p", "tags": []}),
            ("scorer_inverted_scale", ScannerType.SCORER, {"prompt": "p", "scale": {"min": 10, "max": 0}}),
            ("monitor_missing_prompt", ScannerType.MONITOR, {}),
            ("not_a_dict", ScannerType.MONITOR, "just a string"),
        ]
    )
    def test_create_rejects_invalid_scanner_config_per_type(
        self, label: str, scanner_type: ScannerType, scanner_config: Any
    ) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": f"invalid-{label}",
                "scanner_type": scanner_type,
                "scanner_config": scanner_config,
                "model": ScannerModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_config")

    def test_patch_scanner_type_validates_against_existing_config(self) -> None:
        # Existing monitor scanner has {"prompt": "..."}; switching to classifier without tags must 400.
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"scanner_type": ScannerType.CLASSIFIER},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_config")

    def test_patch_can_change_scanner_type_with_matching_config(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"scanner_type": ScannerType.CLASSIFIER, "scanner_config": {"prompt": "p", "tags": ["x"]}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["scanner_type"], ScannerType.CLASSIFIER)

    def test_create_accepts_valid_query(self) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "with-query",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "query": {"filter_test_accounts": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["query"], {"filter_test_accounts": True})

    def test_create_strips_date_fields_from_query(self) -> None:
        # The schedule controls time, not the user.
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "stripped",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "query": {"date_from": "-7d", "date_to": "-1d", "filter_test_accounts": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body_query = resp.json()["query"]
        self.assertNotIn("date_from", body_query)
        self.assertNotIn("date_to", body_query)
        self.assertEqual(body_query["filter_test_accounts"], True)

    def test_create_rejects_invalid_query(self) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "bad-query",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "query": {"this_field_does_not_exist": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "query")

    def test_delete(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.delete(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ReplayScanner.objects.filter(id=scanner.id).exists())

    @parameterized.expand(
        [
            ("enabled", "false", 1),
            ("scanner_type", ScannerType.CLASSIFIER, 1),
            ("emits_signals", "true", 1),
        ]
    )
    def test_filterset(self, field: str, value: str, expected_count: int) -> None:
        if field == "enabled":
            self._create_scanner(name="enabled-scanner")
            self._create_scanner(name="disabled-scanner", enabled=False)
        elif field == "scanner_type":
            self._create_scanner(name="monitor-scanner")
            self._create_scanner(name="classifier-scanner", scanner_type=ScannerType.CLASSIFIER)
        elif field == "emits_signals":
            self._create_scanner(name="silent")
            self._create_scanner(name="loud", emits_signals=True)
        resp = self.client.get(f"{self.scanners_url}?{field}={value}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), expected_count)

    def test_order_by_descending(self) -> None:
        self._create_scanner(name="a-scanner")
        self._create_scanner(name="b-scanner")
        resp = self.client.get(f"{self.scanners_url}?order_by=-name")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["b-scanner", "a-scanner"])


class TestReplayScannerViewSetFeatureFlag(APIBaseTest):
    @property
    def scanners_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/"

    @patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_returns_404_on_list(self, _flag_mock) -> None:
        resp = self.client.get(self.scanners_url)
        self.assertEqual(resp.status_code, 404)

    @patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_returns_404_on_create(self, _flag_mock) -> None:
        resp = self.client.post(self.scanners_url, data={"name": "x"}, format="json")
        self.assertEqual(resp.status_code, 404)

    @patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_off_returns_404_on_estimate(self, _flag_mock) -> None:
        resp = self.client.post(f"{self.scanners_url}estimate/", data={}, format="json")
        self.assertEqual(resp.status_code, 404)


class TestReplayObservationViewSet(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def _create_observation(self, **overrides) -> ReplayObservation:
        defaults = {
            "scanner": self.scanner,
            "session_id": "sess-1",
            "scanner_snapshot": _snapshot_for(self.scanner),
            "triggered_by": ObservationTrigger.SCHEDULE,
        }
        defaults.update(overrides)
        return ReplayObservation.objects.create(**defaults)

    def test_list_observations_for_scanner(self) -> None:
        self._create_observation(session_id="s1")
        self._create_observation(session_id="s2")
        resp = self.client.get(self.observations_url(str(self.scanner.id)))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 2)

    def test_malformed_scanner_id_returns_404(self) -> None:
        resp = self.client.get(self.observations_url("not-a-uuid"))
        self.assertEqual(resp.status_code, 404)

    def test_unknown_scanner_id_returns_404(self) -> None:
        import uuid as _uuid

        resp = self.client.get(self.observations_url(str(_uuid.uuid4())))
        self.assertEqual(resp.status_code, 404)

    def test_other_team_scanner_id_returns_404(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        resp = self.client.get(self.observations_url(str(other_scanner.id)))
        self.assertEqual(resp.status_code, 404)

    def test_list_excludes_observations_from_other_scanner(self) -> None:
        other_scanner = self._create_scanner(name="other-scanner")
        self._create_observation(session_id="ours")
        ReplayObservation.objects.create(
            scanner=other_scanner,
            session_id="theirs",
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        resp = self.client.get(self.observations_url(str(self.scanner.id)))
        sessions = [r["session_id"] for r in resp.json()["results"]]
        self.assertEqual(sessions, ["ours"])

    def test_retrieve_observation(self) -> None:
        obs = self._create_observation()
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}{obs.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["session_id"], obs.session_id)
        self.assertIsNone(resp.json()["scanner_result"])  # null until succeeded

    def test_retrieve_observation_exposes_scanner_result_when_succeeded(self) -> None:
        obs = self._create_observation(
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={
                "model_output": {
                    "scanner_type": "monitor",
                    "verdict": True,
                    "reasoning": "user completed checkout",
                    "confidence": 0.9,
                },
                "signals_count": 0,
            },
        )
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}{obs.id}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["scanner_result"]["signals_count"], 0)
        self.assertEqual(body["scanner_result"]["model_output"]["verdict"], True)
        self.assertEqual(body["scanner_result"]["model_output"]["confidence"], 0.9)

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
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?{field}={value}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), expected_count)

    def test_order_by_created_at_descending(self) -> None:
        first = self._create_observation(session_id="first")
        second = self._create_observation(session_id="second")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?order_by=-created_at")
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertEqual(ids, [str(second.id), str(first.id)])

    def test_pagination(self) -> None:
        for i in range(3):
            self._create_observation(session_id=f"s{i}")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?limit=2")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["results"]), 2)
        self.assertIsNotNone(body.get("next"))


@patch("products.replay_vision.backend.api.scanners.async_to_sync")
@patch("products.replay_vision.backend.api.scanners.sync_connect")
class TestObserveAction(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def observe_url(self, scanner_id: str) -> str:
        return f"{self.scanners_url}{scanner_id}/observe/"

    def test_observe_returns_workflow_id_and_starts_workflow(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_sync_connect.return_value = mock_client
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(self.observe_url(str(self.scanner.id)), data={"session_id": "sess-42"}, format="json")
        self.assertEqual(resp.status_code, 202, resp.json())

        expected_workflow_id = build_apply_scanner_workflow_id(self.scanner.id, "sess-42")
        self.assertEqual(resp.json(), {"workflow_id": expected_workflow_id})

        self.assertFalse(ReplayObservation.objects.filter(scanner=self.scanner, session_id="sess-42").exists())

        mock_async_to_sync.assert_called_once_with(mock_client.start_workflow)
        args, kwargs = start_workflow.call_args
        self.assertEqual(args[0], APPLY_SCANNER_WORKFLOW_NAME)
        self.assertEqual(kwargs["id"], expected_workflow_id)
        self.assertEqual(kwargs["execution_timeout"], timedelta(hours=1))
        inputs = args[1]
        self.assertEqual(inputs.scanner_id, self.scanner.id)
        self.assertEqual(inputs.session_id, "sess-42")
        self.assertEqual(inputs.team_id, self.team.id)
        self.assertEqual(inputs.triggered_by, ObservationTrigger.ON_DEMAND)
        self.assertEqual(inputs.triggered_by_user_id, self.user.id)

    def test_observe_dedup_uses_deterministic_workflow_id(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        first = self.client.post(self.observe_url(str(self.scanner.id)), data={"session_id": "sess-dup"}, format="json")
        second = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": "sess-dup"}, format="json"
        )
        self.assertEqual(first.json()["workflow_id"], second.json()["workflow_id"])

    def test_observe_rejects_missing_session_id(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        resp = self.client.post(self.observe_url(str(self.scanner.id)), data={}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "session_id")

    def test_observe_rejects_too_long_session_id(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        resp = self.client.post(
            self.observe_url(str(self.scanner.id)),
            data={"session_id": "x" * 129},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "session_id")

    def test_observe_workflow_id_fits_observation_column_at_max_input(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Catches widening session_id without re-checking the workflow_id column ceiling.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        max_session_id = "x" * 128

        resp = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": max_session_id}, format="json"
        )
        self.assertEqual(resp.status_code, 202, resp.json())
        workflow_id = resp.json()["workflow_id"]
        max_length = ReplayObservation._meta.get_field("workflow_id").max_length
        assert max_length is not None
        self.assertLessEqual(len(workflow_id), max_length)

    def test_observe_dispatch_failure_returns_503(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock(side_effect=RuntimeError("temporal unavailable"))
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": "sess-broken"}, format="json"
        )
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(ReplayObservation.objects.filter(scanner=self.scanner, session_id="sess-broken").exists())

    def test_observe_workflow_already_started_is_treated_as_success(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        coalesced_workflow_id = build_apply_scanner_workflow_id(self.scanner.id, "sess-coalesce")
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock(
            side_effect=WorkflowAlreadyStartedError(
                workflow_id=coalesced_workflow_id,
                workflow_type=APPLY_SCANNER_WORKFLOW_NAME,
            )
        )
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": "sess-coalesce"}, format="json"
        )
        self.assertEqual(resp.status_code, 202, resp.json())
        self.assertEqual(resp.json(), {"workflow_id": coalesced_workflow_id})

    def test_observe_workflow_already_started_with_mismatched_id_returns_503(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Mismatched workflow_id must not silently 202 under a future id_reuse_policy.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock(
            side_effect=WorkflowAlreadyStartedError(
                workflow_id="some-unrelated-workflow-id",
                workflow_type=APPLY_SCANNER_WORKFLOW_NAME,
            )
        )
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": "sess-mismatch"}, format="json"
        )
        self.assertEqual(resp.status_code, 503, resp.json())


@patch("products.replay_vision.backend.api.scanners.async_to_sync")
@patch("products.replay_vision.backend.api.scanners.sync_connect")
class TestObserveActionFeatureFlag(APIBaseTest):
    def test_flag_off_returns_404(self, _mock_sync_connect: MagicMock, _mock_async_to_sync: MagicMock) -> None:
        with patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            scanner = ReplayScanner.objects.create(
                team=self.team,
                name="off",
                scanner_type=ScannerType.MONITOR,
                scanner_config={"prompt": "p"},
                model=ScannerModel.GEMINI_3_FLASH,
            )
            resp = self.client.post(
                f"/api/environments/{self.team.id}/vision/scanners/{scanner.id}/observe/",
                data={"session_id": "s"},
                format="json",
            )
            self.assertEqual(resp.status_code, 404)


class TestSessionReplayObservationViewSet(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner_a = self._create_scanner(name="scanner-a")
        self.scanner_b = self._create_scanner(name="scanner-b")

    @property
    def session_observations_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/observations/"

    def _create_observation(self, scanner: ReplayScanner, session_id: str) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def test_list_returns_observations_from_every_scanner_for_the_session(self) -> None:
        self._create_observation(self.scanner_a, "sess-target")
        self._create_observation(self.scanner_b, "sess-target")
        self._create_observation(self.scanner_a, "sess-other")

        resp = self.client.get(f"{self.session_observations_url}?session_id=sess-target")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual({r["scanner_id"] for r in results}, {str(self.scanner_a.id), str(self.scanner_b.id)})

    def test_list_requires_session_id(self) -> None:
        resp = self.client.get(self.session_observations_url)
        self.assertEqual(resp.status_code, 400)

    def test_list_excludes_other_teams(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        ReplayObservation.objects.create(
            scanner=other_scanner,
            session_id="sess-target",
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self._create_observation(self.scanner_a, "sess-target")

        resp = self.client.get(f"{self.session_observations_url}?session_id=sess-target")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual([r["scanner_id"] for r in results], [str(self.scanner_a.id)])

    def test_retrieve(self) -> None:
        observation = self._create_observation(self.scanner_a, "sess-target")
        resp = self.client.get(f"{self.session_observations_url}{observation.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], str(observation.id))


class TestReplayScannerEstimateAction(ClickhouseTestMixin, _VisionAPITestCase):
    @property
    def estimate_url(self) -> str:
        return f"{self.scanners_url}estimate/"

    def _ingest_session(self, *, days_ago: float) -> None:
        # HogQL skips non-UUIDv7 `$session_id` values, so the estimate query would return 0 for them.
        first_timestamp = timezone.now() - timedelta(days=days_ago)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=str(uuid7()),
            distinct_id="estimate-distinct-id",
            first_timestamp=first_timestamp,
            last_timestamp=first_timestamp + timedelta(minutes=5),
        )

    @parameterized.expand(
        [
            ("sampling_rate_above_one", {"sampling_rate": 1.5}),
            ("sampling_rate_negative", {"sampling_rate": -0.1}),
        ]
    )
    def test_estimate_rejects_invalid_input(self, _name: str, payload: dict[str, Any]) -> None:
        resp = self.client.post(self.estimate_url, data=payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_estimate_counts_only_in_window_sessions(self) -> None:
        for index in range(3):
            self._ingest_session(days_ago=index + 1)
        self._ingest_session(days_ago=40)

        resp = self.client.post(self.estimate_url, data={}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["matched_sessions_in_window"], 3)
        self.assertEqual(body["window_days"], 30)
        self.assertEqual(body["estimated_observations_per_month"], 3)

    def test_estimate_applies_sampling(self) -> None:
        for index in range(4):
            self._ingest_session(days_ago=index + 1)
        # Anchor 40 days back so `window_days` clamps to a deterministic 30, not the recent data span.
        self._ingest_session(days_ago=40)

        resp = self.client.post(self.estimate_url, data={"sampling_rate": 0.5}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["matched_sessions_in_window"], 4)
        self.assertEqual(body["window_days"], 30)
        self.assertEqual(body["sampling_rate"], 0.5)
        self.assertEqual(body["estimated_observations_per_month"], 2)
