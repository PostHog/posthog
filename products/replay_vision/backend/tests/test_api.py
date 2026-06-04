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
            ("monitor-allow-inconclusive", ScannerType.MONITOR, {"prompt": "p", "allow_inconclusive": True}),
            ("classifier", ScannerType.CLASSIFIER, {"prompt": "p", "tags": ["a", "b"]}),
            ("scorer", ScannerType.SCORER, {"prompt": "p", "scale": {"min": 0, "max": 10}}),
            ("summarizer", ScannerType.SUMMARIZER, {"prompt": "p"}),
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

    def _patch_deny_session_recording(self):
        return patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, **_: resource != "session_recording",
        )

    def test_create_rejected_without_session_recording_read(self) -> None:
        with self._patch_deny_session_recording():
            resp = self.client.post(
                self.scanners_url,
                data={
                    "name": "needs-recording-read",
                    "scanner_type": ScannerType.MONITOR,
                    "scanner_config": {"prompt": "p"},
                    "model": ScannerModel.GEMINI_3_FLASH,
                },
                format="json",
            )
        self.assertEqual(resp.status_code, 403, resp.json())
        self.assertIn("session_recording", resp.json()["detail"])

    def test_patch_rejected_without_session_recording_read(self) -> None:
        scanner = self._create_scanner()
        with self._patch_deny_session_recording():
            resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"name": "renamed"}, format="json")
        self.assertEqual(resp.status_code, 403, resp.json())


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
                    "verdict": "yes",
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
        self.assertEqual(body["scanner_result"]["model_output"]["verdict"], "yes")
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

    def test_stats_status_counts_and_coverage(self) -> None:
        self._create_observation(
            session_id="a",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={
                "model_output": {
                    "scanner_type": "monitor",
                    "verdict": "yes",
                    "reasoning": "r",
                    "confidence": 0.9,
                },
                "signals_count": 0,
            },
        )
        self._create_observation(
            session_id="a-failed",
            status=ObservationStatus.FAILED,
            error_reason="provider_transient:nope",
            completed_at=timezone.now(),
        )
        self._create_observation(
            session_id="b",
            status=ObservationStatus.INELIGIBLE,
            error_reason="too_short:tiny",
            completed_at=timezone.now(),
        )
        self._create_observation(session_id="c")  # pending
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}stats/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status_counts"]["total"], 4)
        self.assertEqual(body["status_counts"]["succeeded"], 1)
        self.assertEqual(body["status_counts"]["failed"], 1)
        self.assertEqual(body["status_counts"]["ineligible"], 1)
        self.assertEqual(body["status_counts"]["in_flight"], 1)
        self.assertEqual(body["status_counts"]["success_rate"], 50)
        self.assertEqual(body["coverage"]["total_sessions"], 4)
        self.assertEqual(body["coverage"]["recent_days"], 14)
        # Monitor scanner: monitor stats populated, classifier/scorer null.
        self.assertEqual(body["monitor"], {"yes_total": 1, "no_total": 0, "inconclusive_total": 0})
        self.assertIsNone(body["classifier"])
        self.assertIsNone(body["scorer"])

    def test_stats_classifier_tag_rankings(self) -> None:
        classifier = self._create_scanner(
            name="intent",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "p", "tags": ["onboarding", "support"], "multi_label": True},
        )
        for idx, (tags, freeform) in enumerate(
            [
                (["onboarding"], []),
                (["onboarding", "support"], ["surprise"]),
                (["support"], ["surprise"]),
                ([], []),
            ]
        ):
            ReplayObservation.objects.create(
                scanner=classifier,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(classifier),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {
                        "scanner_type": "classifier",
                        "tags": tags,
                        "tags_freeform": freeform,
                        "reasoning": "r",
                        "confidence": 0.5,
                    },
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(classifier.id))}stats/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["classifier"]["total_with_tags"], 3)
        self.assertEqual(
            body["classifier"]["fixed_ranked"],
            [{"tag": "onboarding", "count": 2}, {"tag": "support", "count": 2}],
        )
        self.assertEqual(body["classifier"]["freeform_ranked"], [{"tag": "surprise", "count": 2}])
        self.assertEqual(sorted(body["available_tags"]), ["onboarding", "support", "surprise"])
        self.assertIsNone(body["monitor"])
        self.assertIsNone(body["scorer"])

    def test_filterset_status_multi_value(self) -> None:
        self._create_observation(session_id="ok", status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        self._create_observation(
            session_id="bad",
            status=ObservationStatus.FAILED,
            error_reason="x:y",
            completed_at=timezone.now(),
        )
        self._create_observation(session_id="pending")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?status=succeeded,failed")
        self.assertEqual(resp.status_code, 200)
        sessions = sorted(r["session_id"] for r in resp.json()["results"])
        self.assertEqual(sessions, ["bad", "ok"])

    def test_filterset_verdict_multi_value(self) -> None:
        for verdict in ["yes", "no", "inconclusive"]:
            self._create_observation(
                session_id=f"sess-{verdict}",
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {
                        "scanner_type": "monitor",
                        "verdict": verdict,
                        "reasoning": "r",
                        "confidence": 0.5,
                    },
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?verdict=yes,inconclusive")
        self.assertEqual(resp.status_code, 200)
        sessions = sorted(r["session_id"] for r in resp.json()["results"])
        self.assertEqual(sessions, ["sess-inconclusive", "sess-yes"])

    @parameterized.expand(
        [
            ("status=bogus", "status"),
            ("triggered_by=hack", "triggered_by"),
            ("verdict=maybe", "verdict"),
            ("order_by=garbage", "order_by"),
            ("order_by=-result_score_typo", "order_by"),
        ]
    )
    def test_invalid_filter_or_order_returns_400(self, query: str, attr: str) -> None:
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?{query}")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("attr"), attr)

    def test_order_by_result_score_ignores_non_numeric_payloads(self) -> None:
        scorer = self._create_scanner(
            name="frustration",
            scanner_type=ScannerType.SCORER,
            scanner_config={"prompt": "p", "scale": {"min": 0, "max": 100}},
        )
        # Schema drift / bad write: `score` may be a string. The cast must not 500 the request.
        for idx, score in enumerate([3.0, "not-a-number", 1.0]):
            ReplayObservation.objects.create(
                scanner=scorer,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(scorer),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": "scorer", "score": score, "reasoning": "r", "confidence": 0.5},
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?order_by=result_score")
        self.assertEqual(resp.status_code, 200)
        sessions = [r["session_id"] for r in resp.json()["results"]]
        # Numeric scores first (ascending), bad row last via nulls_last.
        self.assertEqual(sessions, ["sess-2", "sess-0", "sess-1"])

    def test_order_by_result_score_numeric(self) -> None:
        scorer = self._create_scanner(
            name="frustration",
            scanner_type=ScannerType.SCORER,
            scanner_config={"prompt": "p", "scale": {"min": 0, "max": 100}},
        )
        for idx, score in enumerate([2.0, 10.0, 1.0]):
            ReplayObservation.objects.create(
                scanner=scorer,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(scorer),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": "scorer", "score": score, "reasoning": "r", "confidence": 0.5},
                    "signals_count": 0,
                },
            )
        # Lexicographic ordering would put "10" before "2"; numeric ordering puts 1 < 2 < 10.
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?order_by=result_score")
        sessions = [r["session_id"] for r in resp.json()["results"]]
        self.assertEqual(sessions, ["sess-2", "sess-0", "sess-1"])
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?order_by=-result_score")
        sessions = [r["session_id"] for r in resp.json()["results"]]
        self.assertEqual(sessions, ["sess-1", "sess-0", "sess-2"])

    def test_order_by_scanner_version_numeric(self) -> None:
        snap_v1 = {**_snapshot_for(self.scanner), "scanner_version": 1}
        snap_v2 = {**_snapshot_for(self.scanner), "scanner_version": 2}
        snap_v10 = {**_snapshot_for(self.scanner), "scanner_version": 10}
        for idx, snap in enumerate([snap_v2, snap_v10, snap_v1]):
            ReplayObservation.objects.create(
                scanner=self.scanner,
                session_id=f"sess-{idx}",
                scanner_snapshot=snap,
                triggered_by=ObservationTrigger.SCHEDULE,
            )
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?order_by=scanner_version")
        sessions = [r["session_id"] for r in resp.json()["results"]]
        self.assertEqual(sessions, ["sess-2", "sess-0", "sess-1"])

    def test_filterset_tags_match_fixed_or_freeform(self) -> None:
        classifier = self._create_scanner(
            name="intent",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "p", "tags": ["onboarding", "support"], "multi_label": True},
        )
        for idx, (tags, freeform) in enumerate(
            [
                (["onboarding"], []),
                (["support"], []),
                ([], ["surprise"]),
                ([], []),
            ]
        ):
            ReplayObservation.objects.create(
                scanner=classifier,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(classifier),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {
                        "scanner_type": "classifier",
                        "tags": tags,
                        "tags_freeform": freeform,
                        "reasoning": "r",
                        "confidence": 0.5,
                    },
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(classifier.id))}?tags=onboarding,surprise")
        self.assertEqual(resp.status_code, 200)
        sessions = sorted(r["session_id"] for r in resp.json()["results"])
        self.assertEqual(sessions, ["sess-0", "sess-2"])

    def test_stats_scorer_summary_and_histogram(self) -> None:
        scorer = self._create_scanner(
            name="frustration",
            scanner_type=ScannerType.SCORER,
            scanner_config={"prompt": "p", "scale": {"min": 0, "max": 10}},
        )
        for idx, score in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
            ReplayObservation.objects.create(
                scanner=scorer,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(scorer),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": "scorer", "score": score, "reasoning": "r", "confidence": 0.5},
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}stats/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        summary = body["scorer"]["summary"]
        self.assertEqual(summary["count"], 5)
        self.assertEqual(summary["min"], 1.0)
        self.assertEqual(summary["max"], 5.0)
        self.assertEqual(summary["median"], 3.0)
        self.assertAlmostEqual(summary["mean"], 3.0)
        histogram = body["scorer"]["histogram"]
        self.assertEqual(sum(histogram["counts"]), 5)
        self.assertEqual(len(histogram["labels"]), len(histogram["counts"]))
        self.assertIsNone(body["monitor"])
        self.assertIsNone(body["classifier"])

    def test_stats_respects_status_filter(self) -> None:
        self._create_observation(session_id="ok", status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        self._create_observation(
            session_id="bad",
            status=ObservationStatus.FAILED,
            error_reason="x:y",
            completed_at=timezone.now(),
        )
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}stats/?status=failed")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status_counts"]["total"], 1)
        self.assertEqual(body["status_counts"]["failed"], 1)
        self.assertEqual(body["status_counts"]["succeeded"], 0)


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
