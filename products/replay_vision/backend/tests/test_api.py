from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.replay_vision.backend.digest import SCANNER_DIGEST_RRULE
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
from products.replay_vision.backend.models.vision_action import VisionAction
from products.replay_vision.backend.queries.scanner_candidate_query import SETTLE_INTERVAL
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for
from products.signals.backend.models import SignalSourceConfig


class _VisionAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        # Scanner saves recompute the volume estimate against ClickHouse; keep CRUD tests off that path.
        self.refresh_estimate_patcher = patch("products.replay_vision.backend.api.scanners.refresh_scanner_estimate")
        self.mock_refresh_estimate = self.refresh_estimate_patcher.start()

    def tearDown(self) -> None:
        self.refresh_estimate_patcher.stop()
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

    def test_create_seeds_sweep_watermark_a_settle_interval_back(self) -> None:
        # The watermark starts one settle-interval before creation so the first sweep isn't a ~settle-interval cold start.
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "watermark-seed",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "did checkout complete?"},
                "model": ScannerModel.GEMINI_3_FLASH,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        scanner = ReplayScanner.objects.get(pk=resp.json()["id"])
        self.assertAlmostEqual(scanner.created_at - scanner.last_swept_at, SETTLE_INTERVAL, delta=timedelta(seconds=5))

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

    @parameterized.expand([("below", -0.1), ("above", 1.5), ("below_sampling_precision", 0.00005)])
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

    @parameterized.expand([("paused", 0.0), ("precision_floor", 0.0001)])
    def test_create_accepts_sampling_rate_boundaries(self, _label: str, value: float) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": f"rate-ok-{value}",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_FLASH,
                "sampling_rate": value,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["sampling_rate"], value)

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

    @parameterized.expand(
        [
            (
                "classifier_empty_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": []},
                "Tag vocabulary must have at least one tag.",
            ),
            (
                "classifier_missing_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p"},
                "Tag vocabulary must have at least one tag.",
            ),
            (
                "classifier_blank_tag",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["bug", "   "]},
                "Tags can't be blank.",
            ),
            (
                "classifier_duplicate_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["Bug", "bug"]},
                "Tags must be unique: 'Bug' and 'bug' are the same tag.",
            ),
            (
                "classifier_slug_colliding_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["login issue", "login_issue"]},
                "Tags must be unique: 'login issue' and 'login_issue' are the same tag.",
            ),
            (
                "classifier_tag_without_alphanumerics",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["!!!"]},
                "Tags must contain letters or numbers.",
            ),
            (
                "monitor_missing_prompt",
                ScannerType.MONITOR,
                {},
                "Prompt is required.",
            ),
            (
                "monitor_explicit_null_prompt",
                ScannerType.MONITOR,
                {"prompt": None},
                "Prompt is required.",
            ),
            (
                "scorer_inverted_scale",
                ScannerType.SCORER,
                {"prompt": "p", "scale": {"min": 10, "max": 0}},
                "Scale max must be greater than min.",
            ),
            (
                "scorer_missing_scale",
                ScannerType.SCORER,
                {"prompt": "p"},
                "Scale is required.",
            ),
            (
                "not_a_dict",
                ScannerType.MONITOR,
                "just a string",
                "Scanner configuration must be a JSON object.",
            ),
            (
                "oversized_prompt",
                ScannerType.MONITOR,
                {"prompt": "p" * 20_001},
                "Prompt can be at most 20,000 characters.",
            ),
            (
                "too_many_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": [f"tag-{i}" for i in range(101)]},
                "Tag vocabulary can have at most 100 tags.",
            ),
            (
                "overlong_tag",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["ok", "x" * 101]},
                "Tags can be at most 100 characters.",
            ),
            (
                "unknown_config_key",
                ScannerType.MONITOR,
                {"prompt": "p", "alow_inconclusive": True},
                "Unknown scanner configuration keys: alow_inconclusive.",
            ),
        ]
    )
    def test_validation_returns_specific_message_per_invalid_config(
        self, label: str, scanner_type: ScannerType, scanner_config: Any, expected_detail: str
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
        body = resp.json()
        detail = body.get("detail", "")
        self.assertNotIn("validation error for", detail)
        self.assertNotIn("errors.pydantic.dev", detail)
        self.assertNotIn("input_value=", detail)
        self.assertEqual(detail, expected_detail)

    def test_patch_rejects_scanner_type_change(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"scanner_type": ScannerType.CLASSIFIER, "scanner_config": {"prompt": "p", "tags": ["x"]}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_type")
        self.assertIn("fixed after creation", resp.json()["detail"])

    def test_patch_accepts_same_scanner_type(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"scanner_type": scanner.scanner_type, "scanner_config": {"prompt": "still a monitor"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())

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
            ("enabled", "disabled", 1),
            ("enabled", "enabled,disabled", 2),
            ("enabled", "true", 1),
            ("enabled", "false", 1),
            ("enabled", "1", 1),
            ("enabled", "0", 1),
            ("scanner_type", ScannerType.CLASSIFIER, 1),
            ("scanner_type", f"{ScannerType.CLASSIFIER},{ScannerType.MONITOR}", 2),
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

    @parameterized.expand(
        [
            ("enabled=bogus", "enabled"),
            ("scanner_type=does_not_exist", "scanner_type"),
            ("order_by=nope", "order_by"),
            ("created_by=alice", "created_by"),
        ]
    )
    def test_invalid_filter_or_order_returns_400(self, query: str, attr: str) -> None:
        resp = self.client.get(f"{self.scanners_url}?{query}")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("attr"), attr)

    @parameterized.expand(
        [
            ("prompt match", "dead", ["beta"]),
            ("description match", "first", ["alpha"]),
            ("case-insensitive name match", "AmMa", ["gamma"]),
        ]
    )
    def test_search_matches_name_description_or_prompt(
        self, _label: str, query: str, expected_names: list[str]
    ) -> None:
        self._create_scanner(name="alpha", description="first scanner")
        self._create_scanner(name="beta", description="something else", scanner_config={"prompt": "find dead ends"})
        self._create_scanner(name="gamma", description="third")
        resp = self.client.get(f"{self.scanners_url}?search={query}")
        self.assertEqual([r["name"] for r in resp.json()["results"]], expected_names)

    def test_created_by_filter_multi_value(self) -> None:
        other_user = User.objects.create_and_join(self.team.organization, "other@example.com", "pw")
        a = self._create_scanner(name="a")
        a.created_by = self.user
        a.save(update_fields=["created_by"])
        b = self._create_scanner(name="b")
        b.created_by = other_user
        b.save(update_fields=["created_by"])
        self._create_scanner(name="c")
        resp = self.client.get(f"{self.scanners_url}?created_by={self.user.id},{other_user.id}")
        names = sorted(r["name"] for r in resp.json()["results"])
        self.assertEqual(names, ["a", "b"])

    def test_order_by_descending(self) -> None:
        self._create_scanner(name="a-scanner")
        self._create_scanner(name="b-scanner")
        resp = self.client.get(f"{self.scanners_url}?order_by=-name")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["b-scanner", "a-scanner"])

    def test_order_by_sampling_rate(self) -> None:
        self._create_scanner(name="low", sampling_rate=0.1)
        self._create_scanner(name="mid", sampling_rate=0.5)
        self._create_scanner(name="high", sampling_rate=1.0)
        resp = self.client.get(f"{self.scanners_url}?order_by=sampling_rate")
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["low", "mid", "high"])

    def test_stats_endpoint_returns_team_wide_counts(self) -> None:
        self._create_scanner(name="m1", scanner_type=ScannerType.MONITOR, enabled=True)
        self._create_scanner(name="m2", scanner_type=ScannerType.MONITOR, enabled=False)
        self._create_scanner(name="c1", scanner_type=ScannerType.CLASSIFIER, enabled=True)
        self._create_scanner(name="s1", scanner_type=ScannerType.SCORER, enabled=False)
        resp = self.client.get(f"{self.scanners_url}stats/?enabled=enabled&scanner_type=monitor")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["enabled"], 2)
        self.assertEqual(body["by_type"]["monitor"], {"enabled": 1, "total": 2})
        self.assertEqual(body["by_type"]["classifier"], {"enabled": 1, "total": 1})
        self.assertEqual(body["by_type"]["scorer"], {"enabled": 0, "total": 1})
        self.assertEqual(body["by_type"]["summarizer"], {"enabled": 0, "total": 0})

    def test_stats_endpoint_respects_per_scanner_access_control(self) -> None:
        self._create_scanner(name="visible")
        hidden = self._create_scanner(name="hidden")
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=hidden.pk),
        ):
            resp = self.client.get(f"{self.scanners_url}stats/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)

    def test_creators_endpoint_respects_per_scanner_access_control(self) -> None:
        other = User.objects.create_and_join(self.team.organization, "hidden@example.com", "pw")
        visible = self._create_scanner(name="visible")
        visible.created_by = self.user
        visible.save(update_fields=["created_by"])
        hidden = self._create_scanner(name="hidden")
        hidden.created_by = other
        hidden.save(update_fields=["created_by"])
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=hidden.pk),
        ):
            resp = self.client.get(f"{self.scanners_url}creators/")
        self.assertEqual(resp.status_code, 200)
        ids = [u["id"] for u in resp.json()["creators"]]
        self.assertEqual(ids, [self.user.id])

    def test_creators_endpoint_returns_distinct_users(self) -> None:
        other = User.objects.create_and_join(self.team.organization, "other@example.com", "pw")
        a = self._create_scanner(name="a")
        a.created_by = self.user
        a.save(update_fields=["created_by"])
        b = self._create_scanner(name="b")
        b.created_by = other
        b.save(update_fields=["created_by"])
        c = self._create_scanner(name="c")
        c.created_by = self.user
        c.save(update_fields=["created_by"])
        self._create_scanner(name="d")

        resp = self.client.get(f"{self.scanners_url}creators/")
        self.assertEqual(resp.status_code, 200)
        ids = sorted(u["id"] for u in resp.json()["creators"])
        self.assertEqual(ids, sorted([self.user.id, other.id]))

    def test_order_by_created_by_falls_back_through_name_then_email(self) -> None:
        alice = User.objects.create_and_join(self.organization, "alice@example.com", None, first_name="Alice")
        bob = User.objects.create_and_join(
            self.organization, "bob@example.com", None, first_name="", last_name="Bobson"
        )
        carol = User.objects.create_and_join(self.organization, "carol@example.com", None, first_name="", last_name="")
        for owner, name in [(alice, "a"), (bob, "b"), (carol, "c")]:
            s = self._create_scanner(name=name)
            s.created_by = owner
            s.save(update_fields=["created_by"])
        resp = self.client.get(f"{self.scanners_url}?order_by=created_by")
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["a", "b", "c"])

    def test_order_by_enabled(self) -> None:
        self._create_scanner(name="on")
        self._create_scanner(name="off", enabled=False)
        resp = self.client.get(f"{self.scanners_url}?order_by=-enabled")
        self.assertEqual([r["name"] for r in resp.json()["results"]], ["on", "off"])

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


class TestScannerDigestProvisioning(_VisionAPITestCase):
    _CREATE_BODY = {
        "name": "checkout-monitor",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "did checkout complete?"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }

    def test_create_provisions_daily_digest(self) -> None:
        resp = self.client.post(self.scanners_url, data=self._CREATE_BODY, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        digest = VisionAction.objects.for_team(self.team.id).get(scanner_id=resp.json()["id"], is_scanner_digest=True)
        self.assertEqual(digest.name, "Daily digest: checkout-monitor")
        self.assertEqual(digest.trigger_config["rrule"], SCANNER_DIGEST_RRULE)
        self.assertEqual(digest.trigger_config["timezone"], self.team.timezone)
        self.assertEqual(digest.delivery_config, [])
        # Synthesis aborts on a null creator, so the digest must carry the scanner's creator.
        self.assertEqual(digest.created_by_id, self.user.id)
        self.assertTrue(digest.enabled)

    def test_no_digest_when_actions_flag_off(self) -> None:
        # Teams without the actions feature must not accrue billable synthesis runs they can't see.
        with patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            side_effect=lambda key, *args, **kwargs: key != "replay-vision-actions",
        ):
            resp = self.client.post(self.scanners_url, data=self._CREATE_BODY, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertFalse(VisionAction.objects.for_team(self.team.id).filter(scanner_id=resp.json()["id"]).exists())

    def test_scanner_creation_survives_digest_failure(self) -> None:
        with patch("products.replay_vision.backend.digest.digest_name_for_scanner", side_effect=RuntimeError("boom")):
            resp = self.client.post(self.scanners_url, data=self._CREATE_BODY, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertFalse(VisionAction.objects.for_team(self.team.id).filter(scanner_id=resp.json()["id"]).exists())


class TestScannerEstimatePersistence(_VisionAPITestCase):
    def _create_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "estimate-persistence",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "p"},
            "model": ScannerModel.GEMINI_3_FLASH,
        }
        payload.update(overrides)
        return payload

    def test_create_refreshes_estimate(self) -> None:
        resp = self.client.post(self.scanners_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.mock_refresh_estimate.assert_called_once()
        self.assertEqual(str(self.mock_refresh_estimate.call_args.args[0].id), resp.json()["id"])

    def test_create_succeeds_when_estimate_refresh_fails(self) -> None:
        self.mock_refresh_estimate.side_effect = RuntimeError("clickhouse down")
        resp = self.client.post(self.scanners_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertIsNone(resp.json()["estimated_monthly_observations"])

    def test_response_exposes_estimated_monthly_observations(self) -> None:
        scanner = self._create_scanner()
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            estimated_monthly_observations=42, estimated_at=timezone.now()
        )
        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.json()["estimated_monthly_observations"], 42)

    @parameterized.expand(
        [
            ("sampling_rate_change", {"sampling_rate": 0.5}, True),
            ("query_change", {"query": {"kind": "RecordingsQuery", "operand": "AND"}}, True),
            ("rename_only", {"name": "renamed"}, False),
            ("sampling_rate_unchanged", {"sampling_rate": 1.0}, False),
            ("disable", {"enabled": False}, False),
        ]
    )
    def test_update_refreshes_only_on_volume_affecting_changes(
        self, _name: str, body: dict[str, Any], expect_refresh: bool
    ) -> None:
        scanner = self._create_scanner(sampling_rate=1.0)
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            estimated_monthly_observations=10, estimated_at=timezone.now()
        )
        self.mock_refresh_estimate.reset_mock()

        resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data=body, format="json")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(self.mock_refresh_estimate.called, expect_refresh)

    @parameterized.expand(
        [
            ("fresh_estimate_skips_inline_refresh", timedelta(hours=1), False),
            ("stale_estimate_refreshes_inline", timedelta(days=2), True),
        ]
    )
    def test_reenabling_refreshes_inline_only_when_stale(
        self, _name: str, estimate_age: timedelta, expect_refresh: bool
    ) -> None:
        scanner = self._create_scanner(enabled=False)
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            estimated_monthly_observations=10, estimated_at=timezone.now() - estimate_age
        )
        self.mock_refresh_estimate.reset_mock()

        resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"enabled": True}, format="json")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(self.mock_refresh_estimate.called, expect_refresh)

    def test_update_backfills_a_never_computed_estimate(self) -> None:
        scanner = self._create_scanner()
        self.mock_refresh_estimate.reset_mock()

        resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"name": "renamed"}, format="json")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.mock_refresh_estimate.assert_called_once()


class TestScannerSignalSourceEnablement(_VisionAPITestCase):
    def _payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "signal-enablement",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "p"},
            "model": ScannerModel.GEMINI_3_FLASH,
        }
        payload.update(overrides)
        return payload

    def _has_source_config(self) -> bool:
        return SignalSourceConfig.objects.filter(team=self.team, source_product="replay_vision").exists()

    def test_creating_with_emits_signals_writes_no_source_config(self) -> None:
        # Scanner findings are self-authorizing — the scanner is the config, so no SignalSourceConfig row is created.
        resp = self.client.post(self.scanners_url, data=self._payload(emits_signals=True), format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        assert not self._has_source_config()

    def test_enabling_emits_signals_on_update_writes_no_source_config(self) -> None:
        scanner = self._create_scanner()
        resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"emits_signals": True}, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        assert not self._has_source_config()

    def test_self_driving_availability_false_without_a_responder_setup(self) -> None:
        resp = self.client.get(f"{self.scanners_url}self_driving_availability/")
        self.assertEqual(resp.status_code, 200, resp.json())
        assert resp.json() == {"available": False}

    def test_self_driving_availability_true_with_an_enabled_signal_source(self) -> None:
        # Any enabled source means there's a responder that would consume scanner findings.
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue", enabled=True
        )
        resp = self.client.get(f"{self.scanners_url}self_driving_availability/")
        self.assertEqual(resp.status_code, 200, resp.json())
        assert resp.json() == {"available": True}

    def test_self_driving_availability_scoped_to_the_requesting_team(self) -> None:
        # Another team's enabled source must not leak availability to this team.
        other = Team.objects.create(organization=self.organization, name="other")
        SignalSourceConfig.objects.create(
            team=other, source_product="error_tracking", source_type="issue", enabled=True
        )
        resp = self.client.get(f"{self.scanners_url}self_driving_availability/")
        self.assertEqual(resp.json(), {"available": False})


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

    @override_settings(SERVER_GATEWAY_INTERFACE="ASGI")
    @patch("products.replay_vision.backend.api.observations.stream_observation_progress")
    def test_progress_endpoint_accepts_event_stream_accept_header(self, mock_stream: MagicMock) -> None:
        # The SSE client sends `Accept: text/event-stream`; without ServerSentEventRenderer on the action,
        # DRF content negotiation rejects it with 406 before the view runs, so no progress ever reaches the
        # page and it falls back to polling. Guard that the negotiated stream stays reachable.
        mock_stream.return_value = iter(["event: observation-complete\ndata: {}\n\n"])
        obs = self._create_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        url = f"/api/projects/{self.team.id}/vision/observations/{obs.id}/progress/"
        resp = self.client.get(url, HTTP_ACCEPT="text/event-stream")
        # A 406 here would mean content negotiation rejected the SSE Accept header before the view ran.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["content-type"], "text/event-stream")
        mock_stream.assert_called_once()

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

    def test_recording_subject_email_exposed(self) -> None:
        self._create_observation(session_id="s1", distinct_id="sub-1", recording_subject_email="subject@acme.com")
        resp = self.client.get(self.observations_url(str(self.scanner.id)))
        self.assertEqual(resp.status_code, 200)
        row = resp.json()["results"][0]
        self.assertEqual(row["distinct_id"], "sub-1")
        self.assertEqual(row["recording_subject_email"], "subject@acme.com")

    def test_recording_subject_email_null_when_unset(self) -> None:
        self._create_observation(session_id="s1")
        resp = self.client.get(self.observations_url(str(self.scanner.id)))
        row = resp.json()["results"][0]
        self.assertIsNone(row["distinct_id"])
        self.assertIsNone(row["recording_subject_email"])

    def test_filter_by_recording_subject(self) -> None:
        self._create_observation(session_id="s1", recording_subject_email="alice@acme.com")
        self._create_observation(session_id="s2", recording_subject_email="bob@other.com")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?recording_subject=ACME")
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["s1"])

    def test_order_by_recording_subject_sorts_nulls_last(self) -> None:
        self._create_observation(session_id="s1", recording_subject_email="zoe@acme.com")
        self._create_observation(session_id="s2", recording_subject_email="alice@acme.com")
        self._create_observation(session_id="s3")  # no subject — sorts last regardless of direction
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?order_by=recording_subject_email")
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["s2", "s1", "s3"])

    def test_order_by_completed_at_descending_sorts_in_flight_rows_last(self) -> None:
        now = timezone.now()
        self._create_observation(
            session_id="done-old",
            status=ObservationStatus.SUCCEEDED,
            completed_at=now - timedelta(hours=2),
        )
        self._create_observation(session_id="done-new", status=ObservationStatus.SUCCEEDED, completed_at=now)
        self._create_observation(
            session_id="in-flight"
        )  # pending, completed_at null — Postgres puts nulls first on DESC by default
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?order_by=-completed_at")
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["done-new", "done-old", "in-flight"])

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

    @parameterized.expand(
        [
            ("single", "a", {"a"}),
            ("multiple", "a,b", {"a", "b"}),
            ("all", "a,b,c", {"a", "b", "c"}),
            ("unknown_ignored", "a,zzz", {"a"}),
            ("no_match", "zzz", set()),
        ]
    )
    def test_filter_by_session_ids(self, _name: str, filter_value: str, expected: set[str]) -> None:
        self._create_observation(session_id="a")
        self._create_observation(session_id="b")
        self._create_observation(session_id="c")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?session_id={filter_value}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r["session_id"] for r in resp.json()["results"]}, expected)

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

    def test_stats_status_counts_with_multiple_rows_per_status(self) -> None:
        for i in range(5):
            self._create_observation(session_id=f"p-{i}", status=ObservationStatus.PENDING)
        for i in range(3):
            self._create_observation(
                session_id=f"yes-{i}",
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
        for i in range(2):
            self._create_observation(
                session_id=f"no-{i}",
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {
                        "scanner_type": "monitor",
                        "verdict": "no",
                        "reasoning": "r",
                        "confidence": 0.9,
                    },
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}stats/")
        body = resp.json()
        self.assertEqual(body["status_counts"]["total"], 10)
        self.assertEqual(body["status_counts"]["succeeded"], 5)
        self.assertEqual(body["status_counts"]["in_flight"], 5)
        self.assertEqual(body["monitor"], {"yes_total": 3, "no_total": 2, "inconclusive_total": 0})

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


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
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
        # On-demand applies carry the scanner id so they count toward the sweep's in-flight cap.
        scanner_attrs = kwargs["search_attributes"]
        self.assertTrue(
            any(p.key.name == "PostHogScannerId" and p.value == str(self.scanner.id) for p in scanner_attrs)
        )

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


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
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


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
class TestRetryActions(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def _create_failed(self, session_id: str) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.FAILED,
            error_reason="internal_error:boom",
            completed_at=timezone.now(),
        )

    def retry_url(self, observation_id: str) -> str:
        return f"{self.observations_url(str(self.scanner.id))}{observation_id}/retry/"

    def test_retry_deletes_row_and_starts_workflow(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_sync_connect.return_value = mock_client
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-retry")

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 202, resp.json())

        expected_workflow_id = build_apply_scanner_workflow_id(self.scanner.id, "sess-retry")
        self.assertEqual(resp.json(), {"workflow_id": expected_workflow_id})
        self.assertFalse(ReplayObservation.objects.filter(id=observation.id).exists())

        args, kwargs = start_workflow.call_args
        self.assertEqual(kwargs["id"], expected_workflow_id)
        inputs = args[1]
        self.assertEqual(inputs.triggered_by, ObservationTrigger.ON_DEMAND)
        self.assertEqual(inputs.triggered_by_user_id, self.user.id)

    def test_retry_rejects_non_failed_statuses(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Plain loop, not @parameterized: class-level @patch mis-orders expanded args.
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        cases = [
            (ObservationStatus.SUCCEEDED, timezone.now()),
            (ObservationStatus.INELIGIBLE, timezone.now()),
            (ObservationStatus.PENDING, None),
        ]
        for status_value, completed_at in cases:
            with self.subTest(status=status_value):
                observation = ReplayObservation.objects.create(
                    scanner=self.scanner,
                    session_id=f"sess-keep-{status_value}",
                    scanner_snapshot=_snapshot_for(self.scanner),
                    triggered_by=ObservationTrigger.SCHEDULE,
                    status=status_value,
                    error_reason="kind:msg" if status_value == ObservationStatus.INELIGIBLE else "",
                    completed_at=completed_at,
                )

                resp = self.client.post(self.retry_url(str(observation.id)))
                self.assertEqual(resp.status_code, 400, resp.json())
                self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
                start_workflow.assert_not_called()

    def test_retry_keeps_row_when_quota_exhausted(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-quota")

        exhausted = MagicMock(exhausted=True, credit_limit=500, period_end=timezone.now())
        with patch("products.replay_vision.backend.api.trigger.compute_quota_snapshot", return_value=exhausted):
            resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 402, resp.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
        start_workflow.assert_not_called()

    def test_retry_dispatch_failure_returns_503_with_row_deleted(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Documented contract: the slot is freed even when the start fails, so the session can be re-scanned.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock(side_effect=RuntimeError("temporal unavailable"))
        observation = self._create_failed("sess-broken")

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 503)
        # `detail` is what the frontend toast surfaces; `error` would be silently dropped.
        self.assertIn("can be scanned again", resp.json()["detail"])
        self.assertFalse(ReplayObservation.objects.filter(id=observation.id).exists())

    def _personal_api_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="retry-test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    def test_retry_scope_enforcement_for_personal_api_keys(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The write scope comes from the @action decorator; losing it would let read-scoped keys retry.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        observation = self._create_failed("sess-scopes")
        read_key = self._personal_api_key(["replay_scanner:read", "session_recording:read"])
        write_key = self._personal_api_key(["replay_scanner:write", "session_recording:read"])

        denied = self.client.post(self.retry_url(str(observation.id)), HTTP_AUTHORIZATION=f"Bearer {read_key}")
        self.assertEqual(denied.status_code, 403, denied.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())

        allowed = self.client.post(self.retry_url(str(observation.id)), HTTP_AUTHORIZATION=f"Bearer {write_key}")
        self.assertEqual(allowed.status_code, 202, allowed.json())

    def test_retry_denied_without_scanner_editor_access(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The session route's get_object only checks the observation row; retry must object-check the scanner.
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-rbac")

        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=lambda obj, required_level=None, **_: not isinstance(obj, ReplayScanner),
        ):
            resp = self.client.post(f"/api/environments/{self.team.id}/vision/observations/{observation.id}/retry/")
        self.assertEqual(resp.status_code, 403, resp.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
        start_workflow.assert_not_called()

    def test_retry_conflict_when_previous_run_still_active(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        observation = self._create_failed("sess-still-running")
        workflow_id = build_apply_scanner_workflow_id(self.scanner.id, "sess-still-running")
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock(
            side_effect=WorkflowAlreadyStartedError(workflow_id=workflow_id, workflow_type=APPLY_SCANNER_WORKFLOW_NAME)
        )

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 409, resp.json())
        # Documented contract: the slot is already freed; the recording can be scanned again shortly.
        self.assertFalse(ReplayObservation.objects.filter(id=observation.id).exists())

    def test_retry_works_on_session_scoped_route(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The replay-page dock retries through /vision/observations/, not the scanner-nested route.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        observation = self._create_failed("sess-dock")

        resp = self.client.post(f"/api/environments/{self.team.id}/vision/observations/{observation.id}/retry/")
        self.assertEqual(resp.status_code, 202, resp.json())
        self.assertFalse(ReplayObservation.objects.filter(id=observation.id).exists())


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

    def test_retrieve_exposes_same_scanner_prev_next_neighbors(self) -> None:
        now = timezone.now()
        old = self._create_observation(self.scanner_a, "s-old")
        mid = self._create_observation(self.scanner_a, "s-mid")
        new = self._create_observation(self.scanner_a, "s-new")
        # A different scanner's observation falling between mid and new must NOT be a neighbor.
        other = self._create_observation(self.scanner_b, "s-other")
        ReplayObservation.objects.filter(pk=old.id).update(created_at=now - timedelta(minutes=2))
        ReplayObservation.objects.filter(pk=mid.id).update(created_at=now - timedelta(minutes=1))
        ReplayObservation.objects.filter(pk=new.id).update(created_at=now)
        ReplayObservation.objects.filter(pk=other.id).update(created_at=now - timedelta(seconds=30))

        body = self.client.get(f"{self.session_observations_url}{mid.id}/").json()
        self.assertEqual(body["previous_observation_id"], str(new.id))  # newer sibling
        self.assertEqual(body["next_observation_id"], str(old.id))  # older sibling

        newest = self.client.get(f"{self.session_observations_url}{new.id}/").json()
        self.assertIsNone(newest["previous_observation_id"])
        self.assertEqual(newest["next_observation_id"], str(mid.id))

        oldest = self.client.get(f"{self.session_observations_url}{old.id}/").json()
        self.assertEqual(oldest["previous_observation_id"], str(mid.id))
        self.assertIsNone(oldest["next_observation_id"])

    def test_retrieve_neighbors_break_ties_on_id_for_same_timestamp(self) -> None:
        ts = timezone.now()
        trio = [self._create_observation(self.scanner_a, f"s-tie-{i}") for i in range(3)]
        ReplayObservation.objects.filter(pk__in=[o.id for o in trio]).update(created_at=ts)
        # Identical created_at falls back to id ASC (the list's tiebreak), so the middle id's neighbors are its siblings.
        lo, mid, hi = sorted(trio, key=lambda o: o.id)
        body = self.client.get(f"{self.session_observations_url}{mid.id}/").json()
        self.assertEqual(body["previous_observation_id"], str(lo.id))
        self.assertEqual(body["next_observation_id"], str(hi.id))


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
            # Clear the scanner eligibility bounds the estimate applies, so these sessions count.
            active_milliseconds=30_000,
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
        # Defaults to the baseline model when the request names none.
        self.assertEqual(body["credits_per_observation"], 5)
        self.assertEqual(body["estimated_credits_per_month"], 15)

    def test_estimate_prices_credits_at_proposed_model(self) -> None:
        for index in range(3):
            self._ingest_session(days_ago=index + 1)
        self._ingest_session(days_ago=40)

        resp = self.client.post(self.estimate_url, data={"model": "gemini-3.5-flash"}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["credits_per_observation"], 15)
        self.assertEqual(body["estimated_credits_per_month"], body["estimated_observations_per_month"] * 15)

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

    def test_estimate_others_sum_is_enabled_only_and_excludes_the_edited_scanner(self) -> None:
        self._ingest_session(days_ago=1)

        def make(name: str, *, enabled: bool, estimate: int) -> ReplayScanner:
            return ReplayScanner.objects.create(
                team=self.team,
                name=name,
                scanner_type=ScannerType.MONITOR,
                scanner_config={"prompt": "p"},
                model=ScannerModel.GEMINI_3_FLASH,
                enabled=enabled,
                estimated_monthly_observations=estimate,
            )

        a = make("a", enabled=True, estimate=100)
        make("b", enabled=True, estimate=250)
        make("disabled", enabled=False, estimate=999)  # disabled scanners don't count

        # New scanner (no scanner_id): others = both enabled scanners, credit-weighted at 5/observation.
        new_body = self.client.post(self.estimate_url, data={}, format="json").json()
        self.assertEqual(new_body["other_enabled_scanners_monthly_credits"], 350 * 5)

        # Editing scanner `a`: its own stored estimate is excluded so the forecast won't double-count it.
        edit_body = self.client.post(self.estimate_url, data={"scanner_id": str(a.id)}, format="json").json()
        self.assertEqual(edit_body["other_enabled_scanners_monthly_credits"], 250 * 5)

    def test_estimate_rejects_scanner_id_outside_the_request_team(self) -> None:
        # A scanner_id from another team (even same org) must be rejected, not silently excluded from the others-sum.
        other_team = Team.objects.create(organization=self.team.organization, name="sibling")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
            enabled=True,
            estimated_monthly_observations=500,
        )
        resp = self.client.post(self.estimate_url, data={"scanner_id": str(other_scanner.id)}, format="json")
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_id")
