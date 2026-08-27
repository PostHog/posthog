from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import requests
from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.tagged_item import set_tags_on_object
from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.tagged_item import TaggedItem
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.redis import get_client
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.experiments.backend.models.experiment import Experiment
from products.replay_vision.backend.api.scanners import ReplayScannerSerializer
from products.replay_vision.backend.api.trigger import WorkflowStartOutcome, start_apply_scanner_workflow
from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.digest import SCANNER_DIGEST_RRULE
from products.replay_vision.backend.enqueue_claims import _scanner_key, _team_key, pending_enqueue_claims_for_team
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerOrigin,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.models.replay_scanner_backfill import ReplayScannerBackfill
from products.replay_vision.backend.models.vision_action import VisionAction
from products.replay_vision.backend.queries import ESTIMATE_STALE_AFTER, SAVE_ESTIMATE_BUDGET
from products.replay_vision.backend.queries.scanner_candidate_query import SETTLE_INTERVAL
from products.replay_vision.backend.quota import BillingPeriod, _current_period_bounds
from products.replay_vision.backend.scanner_draft import DraftError, ScannerDraft
from products.replay_vision.backend.search import ObservationMatch
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
    on_demand_priority,
)
from products.replay_vision.backend.tests.helpers import (
    create_experiment,
    seed_scanner_spend,
    snapshot_for as _snapshot_for,
)
from products.signals.backend.facade.api import SignalSourceSliceOutcomes
from products.signals.backend.models import SignalSourceConfig


class _VisionAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Scanner saves recompute the volume estimate against ClickHouse; keep CRUD tests off that path.
        self.refresh_estimate_patcher = patch("products.replay_vision.backend.api.scanners.refresh_scanner_estimate")
        self.mock_refresh_estimate = self.refresh_estimate_patcher.start()

    def tearDown(self) -> None:
        self.refresh_estimate_patcher.stop()
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
            "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
            "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
            model=ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "Add at least one category.",
            ),
            (
                "classifier_missing_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p"},
                "Add at least one category.",
            ),
            (
                "classifier_blank_tag",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["bug", "   "]},
                "Categories can't be blank.",
            ),
            (
                "classifier_duplicate_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["Bug", "bug"]},
                "Categories must be unique: 'Bug' and 'bug' are the same category.",
            ),
            (
                "classifier_slug_colliding_tags",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["login issue", "login_issue"]},
                "Categories must be unique: 'login issue' and 'login_issue' are the same category.",
            ),
            (
                "classifier_tag_without_alphanumerics",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["!!!"]},
                "Categories must contain letters or numbers.",
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
                "You can have at most 100 categories.",
            ),
            (
                "overlong_tag",
                ScannerType.CLASSIFIER,
                {"prompt": "p", "tags": ["ok", "x" * 101]},
                "Categories can be at most 100 characters.",
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
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

    def test_patching_the_credit_limit_persists_and_rejects_zero(self) -> None:
        scanner = self._create_scanner()
        url = f"{self.scanners_url}{scanner.id}/"

        resp = self.client.patch(url, data={"credit_limit": 500}, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        scanner.refresh_from_db()
        self.assertEqual(scanner.credit_limit, 500)

        resp = self.client.patch(url, data={"credit_limit": 0}, format="json")
        self.assertEqual(resp.status_code, 400, resp.json())

    def test_changing_the_credit_limit_rearms_the_limit_notification(self) -> None:
        # The scanner already notified this period; raising the limit makes the next exhaustion news
        # again, while an unrelated edit leaves the stamp alone.
        scanner = self._create_scanner()
        stamp = datetime(2026, 8, 1, tzinfo=UTC)
        ReplayScanner.objects.filter(pk=scanner.pk).update(credit_limit=500, limit_notified_period_start=stamp)
        url = f"{self.scanners_url}{scanner.id}/"

        resp = self.client.patch(url, data={"name": "renamed, limit untouched"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        scanner.refresh_from_db()
        self.assertEqual(scanner.limit_notified_period_start, stamp)

        resp = self.client.patch(url, data={"credit_limit": 1_000}, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        scanner.refresh_from_db()
        self.assertIsNone(scanner.limit_notified_period_start)

    def test_create_accepts_valid_query(self) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "with-query",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_7_FLASH,
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
                "model": ScannerModel.GEMINI_3_7_FLASH,
                "query": {"date_from": "-7d", "date_to": "-1d", "filter_test_accounts": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body_query = resp.json()["query"]
        self.assertNotIn("date_from", body_query)
        self.assertNotIn("date_to", body_query)
        self.assertEqual(body_query["filter_test_accounts"], True)

    @parameterized.expand(
        [
            ("unknown_field", {"this_field_does_not_exist": True}),
            # An oversized query is copied into every observation's snapshot, so it is capped on save.
            ("oversized", {"distinct_ids": ["x" * 1_000 for _ in range(100)]}),
        ]
    )
    def test_create_rejects_invalid_query(self, _name: str, query: dict) -> None:
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "bad-query",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": "p"},
                "model": ScannerModel.GEMINI_3_7_FLASH,
                "query": query,
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
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
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
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
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

    def _patch_deny_resource(self, denied: str):
        return patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, **_: resource != denied,
        )

    def _patch_deny_session_recording(self):
        return self._patch_deny_resource("session_recording")

    def test_create_rejected_without_session_recording_read(self) -> None:
        with self._patch_deny_session_recording():
            resp = self.client.post(
                self.scanners_url,
                data={
                    "name": "needs-recording-read",
                    "scanner_type": ScannerType.MONITOR,
                    "scanner_config": {"prompt": "p"},
                    "model": ScannerModel.GEMINI_3_7_FLASH,
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

    @parameterized.expand(
        [
            ("impact", "get"),
            ("affected_cohort", "post"),
        ]
    )
    def test_recording_derived_action_rejected_without_session_recording_read(self, url_path: str, method: str) -> None:
        scanner = self._create_scanner()
        with self._patch_deny_session_recording():
            resp = getattr(self.client, method)(f"{self.scanners_url}{scanner.id}/{url_path}/", format="json")
        self.assertEqual(resp.status_code, 403, resp.json())
        self.assertIn("session_recording", resp.json()["detail"])

    def test_affected_cohort_rejected_without_cohort_edit_access(self) -> None:
        scanner = self._create_scanner()
        with self._patch_deny_resource("cohort"):
            resp = self.client.post(f"{self.scanners_url}{scanner.id}/affected_cohort/", format="json")
        self.assertEqual(resp.status_code, 403, resp.json())
        self.assertIn("cohort", resp.json()["detail"])


class TestReplayScannerTags(_VisionAPITestCase):
    def _scanner_payload(self, name: str, **extra: Any) -> dict[str, Any]:
        return {
            "name": name,
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "did checkout complete?"},
            "model": ScannerModel.GEMINI_3_7_FLASH,
            **extra,
        }

    def _tag_names(self, scanner_id: str) -> list[str]:
        return sorted(
            TaggedItem.objects.filter(replay_scanner_id=scanner_id).values_list("tag__name", flat=True),
        )

    @parameterized.expand(
        [
            ("with_tags", ["Checkout ", "funnel"], ["checkout", "funnel"]),
            ("without_tags", None, []),
        ]
    )
    def test_create_persists_tags(self, _name: str, tags: list[str] | None, expected: list[str]) -> None:
        payload = self._scanner_payload("tagged-scanner")
        if tags is not None:
            payload["tags"] = tags
        resp = self.client.post(self.scanners_url, data=payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(sorted(resp.json()["tags"]), expected)
        self.assertEqual(self._tag_names(resp.json()["id"]), expected)

    @parameterized.expand(
        [
            ("replace", ["b", "c"], ["b", "c"]),
            ("clear", [], []),
            ("untouched_when_absent", None, ["a", "b"]),
        ]
    )
    def test_patch_tags(self, _name: str, tags: list[str] | None, expected: list[str]) -> None:
        scanner = self._create_scanner()
        set_tags_on_object(["a", "b"], scanner)
        payload: dict[str, Any] = {"description": "updated"}
        if tags is not None:
            payload["tags"] = tags
        resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data=payload, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["description"], "updated")
        self.assertEqual(sorted(resp.json()["tags"]), expected)
        self.assertEqual(self._tag_names(str(scanner.id)), expected)

    @parameterized.expand(
        [
            ("comma_in_tag", ["checkout,production"]),
            ("too_many_tags", [f"tag-{i}" for i in range(33)]),
            ("tag_too_long", ["x" * 256]),
        ]
    )
    def test_create_rejects_invalid_tags(self, _name: str, tags: list[str]) -> None:
        resp = self.client.post(self.scanners_url, data=self._scanner_payload("bad-tags", tags=tags), format="json")
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(TaggedItem.objects.count(), 0)

    def test_list_filters_by_tags(self) -> None:
        both = self._create_scanner(name="both-tags")
        set_tags_on_object(["alpha", "beta"], both)
        beta_only = self._create_scanner(name="beta-only")
        set_tags_on_object(["beta"], beta_only)
        self._create_scanner(name="untagged")

        resp = self.client.get(self.scanners_url, {"tags": "alpha"})
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([s["name"] for s in resp.json()["results"]], ["both-tags"])

        # Writes store tagify()d names, so a mixed-case filter value must still match.
        resp = self.client.get(self.scanners_url, {"tags": "Alpha "})
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([s["name"] for s in resp.json()["results"]], ["both-tags"])

        # A scanner matching several requested tags must not appear once per match.
        resp = self.client.get(self.scanners_url, {"tags": "alpha,beta"})
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(sorted(s["name"] for s in resp.json()["results"]), ["beta-only", "both-tags"])

    @parameterized.expand(
        [
            ("changed", ["b"], ["replay_vision_scanner_edited"]),
            ("unchanged", ["a"], []),
            ("unchanged_after_tagify", ["A "], []),
        ]
    )
    def test_tags_only_patch_reports_edit_only_on_change(
        self, _name: str, tags: list[str], expected_events: list[str]
    ) -> None:
        scanner = self._create_scanner()
        set_tags_on_object(["a"], scanner)
        with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
            resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"tags": tags}, format="json")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([call.args[1] for call in report.call_args_list], expected_events)
        if expected_events:
            self.assertEqual(report.call_args.args[2]["edited_fields"], ["tags"])

    def test_create_rolls_back_scanner_when_tag_write_fails(self) -> None:
        with patch("posthog.api.tagged_item.set_tags_on_object", side_effect=RuntimeError("boom")):
            resp = self.client.post(self.scanners_url, data=self._scanner_payload("atomic", tags=["a"]), format="json")
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(ReplayScanner.objects.filter(team=self.team, name="atomic").exists())

    def test_update_rolls_back_columns_when_tag_write_fails(self) -> None:
        scanner = self._create_scanner(description="before")
        with patch("posthog.api.tagged_item.set_tags_on_object", side_effect=RuntimeError("boom")):
            resp = self.client.patch(
                f"{self.scanners_url}{scanner.id}/", data={"description": "after", "tags": ["a"]}, format="json"
            )
        self.assertEqual(resp.status_code, 500)
        scanner.refresh_from_db()
        self.assertEqual(scanner.description, "before")

    def test_list_tag_serialization_is_constant_queries(self) -> None:
        first = self._create_scanner(name="scanner-0")
        set_tags_on_object(["alpha"], first)
        self.client.get(self.scanners_url)  # Warm request-scoped caches so both captures compare cleanly.
        with CaptureQueriesContext(connection) as one_row:
            self.assertEqual(self.client.get(self.scanners_url).status_code, 200)
        for i in range(1, 5):
            scanner = self._create_scanner(name=f"scanner-{i}")
            set_tags_on_object(["alpha", f"tag-{i}"], scanner)
        with CaptureQueriesContext(connection) as five_rows:
            self.assertEqual(self.client.get(self.scanners_url).status_code, 200)
        self.assertEqual(len(one_row.captured_queries), len(five_rows.captured_queries))


class TestScannerExperimentTargeting(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.experiment = create_experiment(self.team, "checkout-redesign")
        self.targeting = {
            "experiment_id": self.experiment.id,
            "variant": "test",
        }

    def _create_payload(self, name: str, **extra: Any) -> dict[str, Any]:
        return {
            "name": name,
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "p"},
            "model": ScannerModel.GEMINI_3_7_FLASH,
            **extra,
        }

    def test_experiment_targeting_round_trips_and_clears(self) -> None:
        resp = self.client.post(
            self.scanners_url, data=self._create_payload("ctx", experiment_targeting=self.targeting), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["experiment_targeting"], self.targeting)

        scanner_id = resp.json()["id"]
        resp = self.client.patch(
            f"{self.scanners_url}{scanner_id}/", data={"experiment_targeting": None}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertIsNone(resp.json()["experiment_targeting"])

    @parameterized.expand(
        [
            ("missing_experiment", {"variant": "test"}),
            ("bad_experiment_id", {"experiment_id": 0, "variant": "test"}),
            ("blank_variant", {"experiment_id": 9, "variant": ""}),
        ]
    )
    def test_experiment_targeting_rejects_malformed(self, _name: str, targeting: dict[str, Any]) -> None:
        resp = self.client.post(
            self.scanners_url, data=self._create_payload("bad-ctx", experiment_targeting=targeting), format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        # The field's nested validation reports the exact offending key (e.g.
        # experiment_targeting__variant), so match on the prefix rather than the exact attr.
        self.assertTrue(resp.json()["attr"].startswith("experiment_targeting"), resp.json())

    def test_partial_update_cannot_save_a_half_filled_targeting(self) -> None:
        # PATCH makes the parent serializer partial; the custom field validates every write through
        # a fresh non-partial serializer, so a half-filled object can't persist.
        scanner = self._create_scanner(name="patch-me", experiment_targeting=self.targeting)
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"experiment_targeting": {"variant": "control"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        scanner.refresh_from_db()
        self.assertEqual(scanner.experiment_targeting, self.targeting)

    def test_rejects_an_experiment_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        foreign = create_experiment(other_team, "foreign-flag")
        resp = self.client.post(
            self.scanners_url,
            data=self._create_payload(
                "cross-team", experiment_targeting={**self.targeting, "experiment_id": foreign.id}
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_filters_by_experiment_id(self) -> None:
        other = create_experiment(self.team, "other-flag")
        self._create_scanner(name="for-exp", experiment_targeting=self.targeting)
        self._create_scanner(name="for-other-exp", experiment_targeting={**self.targeting, "experiment_id": other.id})
        self._create_scanner(name="no-context")

        resp = self.client.get(f"{self.scanners_url}?experiment_id={self.experiment.id}")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([row["name"] for row in resp.json()["results"]], ["for-exp"])

    @parameterized.expand(
        [
            ("superscript", "\u00b2"),
            ("zero", "0"),
            ("negative", "-1"),
            ("word", "abc"),
            # One past the Postgres bigint max: feeding it to the id lookup would raise
            # NumericValueOutOfRange (a 500) rather than the 400 a malformed filter should get.
            ("above_bigint_max", "9223372036854775808"),
        ]
    )
    def test_list_filter_rejects_non_positive_integers(self, _name: str, value: str) -> None:
        resp = self.client.get(f"{self.scanners_url}?experiment_id={value}")
        self.assertEqual(resp.status_code, 400)


class TestScannerLifecycleTelemetry(_VisionAPITestCase):
    def test_create_reports_config_choices(self) -> None:
        # Launch dashboards read these config choices, so a dropped property or a silent non-fire
        # makes that read a lie. Asserted at the capture boundary, where the source tag lands.
        with patch("posthoganalytics.capture") as capture:
            resp = self.client.post(
                self.scanners_url,
                data={
                    "name": "telemetry-create",
                    "scanner_type": ScannerType.MONITOR,
                    "scanner_config": {"prompt": "did checkout complete?"},
                    "model": ScannerModel.GEMINI_3_7_FLASH,
                    "sampling_rate": 0.25,
                    "query": {"kind": "RecordingsQuery", "events": [{"id": "$pageview"}]},
                },
                format="json",
            )

        self.assertEqual(resp.status_code, 201, resp.json())
        created = [
            call for call in capture.call_args_list if call.kwargs.get("event") == "replay_vision_scanner_created"
        ]
        self.assertEqual(len(created), 1)
        properties = created[0].kwargs["properties"]
        self.assertEqual(properties["scanner_type"], ScannerType.MONITOR)
        self.assertEqual(properties["model"], ScannerModel.GEMINI_3_7_FLASH)
        self.assertEqual(properties["credits_per_observation"], 15)
        self.assertEqual(properties["sampling_rate"], 0.25)
        self.assertTrue(properties["has_filters"])
        self.assertTrue(properties["enabled"])
        self.assertEqual(properties["organization_id"], str(self.team.organization_id))
        # Session auth resolves to "web" (the app UI), MCP callers to "mcp".
        self.assertEqual(properties["source"], "web")

    @parameterized.expand(
        [
            ("disable", True, False, "replay_vision_scanner_disabled"),
            ("enable", False, True, "replay_vision_scanner_enabled"),
        ]
    )
    def test_enabled_transition_reports_once(self, _name: str, before: bool, after: bool, event: str) -> None:
        # A pure enable/disable toggle fires the transition event only, not the config-edit event.
        scanner = self._create_scanner(enabled=before)
        with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
            resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"enabled": after}, format="json")

        self.assertEqual(resp.status_code, 200, resp.json())
        report.assert_called_once()
        self.assertEqual(report.call_args.args[1], event)

    @parameterized.expand(
        [
            ("rename", {"name": "renamed"}, ["replay_vision_scanner_edited"]),
            ("no_op", {}, []),
        ]
    )
    def test_full_body_save_reports_only_actually_changed_fields(
        self, _name: str, mutation: dict[str, Any], expected_events: list[str]
    ) -> None:
        # The UI PATCHes the entire form on save, so submitted-but-unchanged fields must not be
        # reported as edits and a save that changes nothing must not fire at all.
        scanner = self._create_scanner(enabled=True)
        body = {
            "name": scanner.name,
            "scanner_config": scanner.scanner_config,
            "model": scanner.model,
            "sampling_rate": scanner.sampling_rate,
            "enabled": scanner.enabled,
            **mutation,
        }
        with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
            resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data=body, format="json")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([call.args[1] for call in report.call_args_list], expected_events)
        if expected_events:
            self.assertEqual(report.call_args.args[2]["edited_fields"], sorted(mutation.keys()))

    @parameterized.expand(
        [
            ("drafted", None, 200, True),
            ("model_failed", DraftError(), 503, False),
        ]
    )
    def test_draft_reports_outcome(
        self, _name: str, error: Exception | None, expected_status: int, expected_success: bool
    ) -> None:
        # A draft that reports nothing would read as user abandonment instead of a model failure.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        drafted = ScannerDraft(
            name="stuck-in-onboarding",
            description="Sessions where onboarding stalls",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user get stuck?"},
            rationale="Onboarding drop-off is the stated goal",
            query={"kind": "RecordingsQuery", "events": [{"id": "$pageview"}]},
        )
        goal = "find users who get stuck in onboarding"
        with (
            patch(
                "products.replay_vision.backend.api.scanners.draft_scanner_from_goal",
                side_effect=error,
                return_value=drafted,
            ),
            patch("products.replay_vision.backend.api.scanners.report_user_action") as report,
        ):
            resp = self.client.post(f"{self.scanners_url}draft/", data={"goal": goal}, format="json")

        self.assertEqual(resp.status_code, expected_status, resp.json())
        drafted_events = [call for call in report.call_args_list if call.args[1] == "replay_vision_scanner_drafted"]
        self.assertEqual(len(drafted_events), 1)
        properties = drafted_events[0].args[2]
        self.assertEqual(properties["success"], expected_success)
        self.assertEqual(properties["goal_length"], len(goal))
        # The goal is customer text; only its length may ride along.
        self.assertNotIn("goal", properties)


class TestScannerDigestProvisioning(_VisionAPITestCase):
    _CREATE_BODY = {
        "name": "checkout-monitor",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "did checkout complete?"},
        "model": ScannerModel.GEMINI_3_7_FLASH,
    }

    def test_create_provisions_daily_digest(self) -> None:
        resp = self.client.post(self.scanners_url, data=self._CREATE_BODY, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        digest = VisionAction.objects.for_team(self.team.id).get(scanner_id=resp.json()["id"], is_scanner_digest=True)
        self.assertEqual(digest.name, "Featured digest: checkout-monitor")
        self.assertEqual(digest.trigger_config["rrule"], SCANNER_DIGEST_RRULE)
        self.assertEqual(digest.trigger_config["timezone"], self.team.timezone)
        self.assertEqual(digest.delivery_config, [])
        # Synthesis aborts on a null creator, so the digest must carry the scanner's creator.
        self.assertEqual(digest.created_by_id, self.user.id)
        self.assertTrue(digest.enabled)

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
            "model": ScannerModel.GEMINI_3_7_FLASH,
        }
        payload.update(overrides)
        return payload

    def test_create_refreshes_estimate(self) -> None:
        resp = self.client.post(self.scanners_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        self.mock_refresh_estimate.assert_called_once()
        self.assertEqual(str(self.mock_refresh_estimate.call_args.args[0].id), resp.json()["id"])
        # A save blocks the request, so it takes the tighter clock, and it persists the number, so it
        # keeps the full week.
        self.assertEqual(self.mock_refresh_estimate.call_args.kwargs["budget"], SAVE_ESTIMATE_BUDGET)

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
            ("fresh_estimate_skips_inline_refresh", ESTIMATE_STALE_AFTER - timedelta(hours=1), False),
            ("stale_estimate_refreshes_inline", ESTIMATE_STALE_AFTER + timedelta(hours=1), True),
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
            "model": ScannerModel.GEMINI_3_7_FLASH,
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

    def test_list_filters_by_date_range(self) -> None:
        self._create_observation(session_id="recent")
        old = self._create_observation(session_id="old")
        ReplayObservation.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))

        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?date_from=-7d")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["recent"])

        old_day = (timezone.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?date_from={old_day}&date_to={old_day}")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["old"])

        # Relative date_to stays an exact bound instead of extending to end of day.
        resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}?date_to=-1h")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["old"])

    def test_list_date_range_bounds_use_project_timezone(self) -> None:
        self.team.timezone = "US/Pacific"
        self.team.save()
        # 05:00 UTC is 21:00 the previous day in Pacific; 20:00 UTC is 12:00 the same day.
        previous_day = self._create_observation(session_id="pacific-previous-day")
        ReplayObservation.objects.filter(pk=previous_day.pk).update(created_at=datetime(2026, 3, 3, 5, 0, tzinfo=UTC))
        same_day = self._create_observation(session_id="pacific-same-day")
        ReplayObservation.objects.filter(pk=same_day.pk).update(created_at=datetime(2026, 3, 3, 20, 0, tzinfo=UTC))

        base_url = self.observations_url(str(self.scanner.id))
        resp = self.client.get(f"{base_url}?date_from=2026-03-03&date_to=2026-03-03")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["pacific-same-day"])

        resp = self.client.get(f"{base_url}?date_from=2026-03-02&date_to=2026-03-02")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["pacific-previous-day"])

    def test_retrieve_with_filters_resolves_object_and_scopes_neighbors_only(self) -> None:
        observation = self._create_observation(session_id="s-pending")
        self._create_observation(session_id="s-other")

        url = f"{self.observations_url(str(self.scanner.id))}{observation.id}/?status=succeeded"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.json())
        body = resp.json()
        self.assertEqual(body["id"], str(observation.id))
        self.assertIsNone(body["previous_observation_id"])
        self.assertIsNone(body["next_observation_id"])

    @parameterized.expand(
        [
            ("in_flight_poll_tick", ObservationStatus.PENDING, []),
            ("terminal_result", ObservationStatus.SUCCEEDED, ["replay_vision_observation_viewed"]),
        ]
    )
    def test_retrieve_reports_viewed_only_for_terminal_observations(
        self, _name: str, status_value: ObservationStatus, expected_events: list[str]
    ) -> None:
        # An in-flight fetch is a poll tick (the scene polls every few seconds), not a person viewing results.
        completed_at = timezone.now() if status_value == ObservationStatus.SUCCEEDED else None
        observation = self._create_observation(session_id="viewed", status=status_value, completed_at=completed_at)
        with patch("products.replay_vision.backend.api.observations.report_user_action") as report:
            resp = self.client.get(f"{self.observations_url(str(self.scanner.id))}{observation.id}/")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([call.args[1] for call in report.call_args_list], expected_events)

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
            model=ScannerModel.GEMINI_3_7_FLASH,
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
        self.assertIsNone(body["summarizer"])

    def test_stats_summarizer_facet_rankings(self) -> None:
        summarizer = self._create_scanner(
            name="journeys",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "p", "length": "medium"},
        )
        for idx, (friction, keywords) in enumerate(
            [
                # Stored rows can repeat a term within one summary; rankings must count it once.
                (["checkout stalls", "checkout stalls"], ["checkout", "checkout"]),
                (["checkout stalls", "filter reset"], ["checkout", "filters"]),
                # Keywords without friction: the friction rate's numerator and denominator must differ here.
                ([], ["browsing"]),
                ([], []),
            ]
        ):
            ReplayObservation.objects.create(
                scanner=summarizer,
                session_id=f"sess-{idx}",
                scanner_snapshot=_snapshot_for(summarizer),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {
                        "scanner_type": "summarizer",
                        "title": "t",
                        "summary": "s",
                        "friction_points": friction,
                        "keywords": keywords,
                        "confidence": 0.5,
                    },
                    "signals_count": 0,
                },
            )
        resp = self.client.get(f"{self.observations_url(str(summarizer.id))}stats/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["summarizer"]["total_with_facets"], 3)
        self.assertEqual(body["summarizer"]["total_with_friction"], 2)
        self.assertEqual(
            body["summarizer"]["friction_ranked"],
            [{"term": "checkout stalls", "count": 2}, {"term": "filter reset", "count": 1}],
        )
        self.assertEqual(
            body["summarizer"]["keyword_ranked"],
            [{"term": "checkout", "count": 2}, {"term": "browsing", "count": 1}, {"term": "filters", "count": 1}],
        )
        self.assertIsNone(body["classifier"])

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
            ("min_score=low", "min_score"),
            ("max_score=high", "max_score"),
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

    def _create_scorer_with_scores(self, scores: list[Any]) -> ReplayScanner:
        scorer = self._create_scanner(
            name="frustration",
            scanner_type=ScannerType.SCORER,
            scanner_config={"prompt": "p", "scale": {"min": 0, "max": 10}},
        )
        for idx, score in enumerate(scores):
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
        return scorer

    @parameterized.expand(
        [
            ("at_least", "min_score=7", ["sess-1", "sess-3"]),
            ("at_most", "max_score=3", ["sess-0", "sess-2"]),
            ("range", "min_score=3&max_score=7", ["sess-0", "sess-3"]),
            # Bounds are inclusive, and 10 must not lose to a lexicographic comparison against 7.
            ("boundary", "min_score=10", ["sess-1"]),
        ]
    )
    def test_filterset_score_bounds(self, _name: str, query: str, expected: list[str]) -> None:
        scorer = self._create_scorer_with_scores([3.0, 10.0, 0.5, 7.0])
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?{query}")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(sorted(r["session_id"] for r in resp.json()["results"]), expected)

    def test_filterset_score_bounds_exclude_rows_without_a_numeric_score(self) -> None:
        # A pending run has no result at all, and schema drift can leave `score` a string; neither may 500 or match.
        scorer = self._create_scorer_with_scores([5.0, "not-a-number"])
        ReplayObservation.objects.create(
            scanner=scorer,
            session_id="sess-pending",
            scanner_snapshot=_snapshot_for(scorer),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?min_score=0&max_score=10")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["sess-0"])

    def test_filterset_score_bounds_combine_with_ordering(self) -> None:
        # Both annotate the score off the same JSONB path; applying them together must not collide.
        scorer = self._create_scorer_with_scores([3.0, 10.0, 0.5, 7.0])
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}?min_score=3&order_by=-result_score")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["sess-1", "sess-3", "sess-0"])

    def test_stats_respect_score_bounds(self) -> None:
        # The scorer stats embed the filtered queryset into raw SQL, so the annotation-based
        # filter must survive that path, not just the plain list.
        scorer = self._create_scorer_with_scores([3.0, 10.0, 0.5, 7.0])
        resp = self.client.get(f"{self.observations_url(str(scorer.id))}stats/?min_score=7")
        self.assertEqual(resp.status_code, 200, resp.json())
        body = resp.json()
        self.assertEqual(body["status_counts"]["total"], 2)
        self.assertEqual(body["status_counts"]["succeeded"], 2)

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
        # Claims from earlier tests' mocked starts are never released by an activity.
        get_client().delete(_team_key(self.team.id), _scanner_key(self.scanner.id))

    def observe_url(self, scanner_id: str) -> str:
        return f"{self.scanners_url}{scanner_id}/observe/"

    def test_no_scan_entrypoint_starts_without_ai_consent(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # This gate went in per-endpoint and was missed twice, on bulk_observe and then observe. Both
        # returned 202 for a scan that never ran, because create_observation fails closed on consent
        # once the workflow is already going. Covering all of them together is what stops a third.
        # Plain loop, not @parameterized: class-level @patch mis-orders expanded args.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        cases = [
            (f"{self.scanners_url}{self.scanner.id}/observe/", {"session_id": "s1"}),
            (f"{self.scanners_url}{self.scanner.id}/bulk_observe/", {"session_ids": ["s1"]}),
            (f"{self.scanners_url}inline_scan/", {"session_ids": ["s1"], "prompt": "did it fail?"}),
        ]
        for url, body in cases:
            resp = self.client.post(url, data=body, format="json")
            self.assertEqual(resp.status_code, 400, f"{url}: {resp.json()}")
        start_workflow.assert_not_called()

    def test_a_settled_session_returns_the_existing_observation_and_starts_nothing(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A terminal row owns the (scanner, session) slot for good, so starting a workflow would claim
        # an enqueue slot and burn a run only to lose the INSERT and hand back this same row.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        existing = ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="sess-settled",
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
        )

        resp = self.client.post(
            self.observe_url(str(self.scanner.id)), data={"session_id": "sess-settled"}, format="json"
        )

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["observation_id"], str(existing.id))
        start_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("row_persisted_drops_duplicate_claim", True, 0),
            ("row_not_yet_persisted_keeps_claim", False, 1),
        ]
    )
    def test_already_running_claim_follows_row_existence(
        self,
        mock_sync_connect: MagicMock,
        mock_async_to_sync: MagicMock,
        _name: str,
        row_exists: bool,
        expected_claims: int,
    ) -> None:
        # Resubmitting an active session must not mint a phantom claim on top of its persisted row,
        # but a claim for a run still inside the enqueue gap has to survive.
        session_id = "sess-running"
        if row_exists:
            ReplayObservation.objects.create(
                scanner=self.scanner,
                session_id=session_id,
                scanner_snapshot=_snapshot_for(self.scanner),
                triggered_by=ObservationTrigger.ON_DEMAND,
                status=ObservationStatus.PENDING,
            )
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock(
            side_effect=WorkflowAlreadyStartedError(
                workflow_id=build_apply_scanner_workflow_id(self.scanner.id, session_id),
                workflow_type=APPLY_SCANNER_WORKFLOW_NAME,
            )
        )

        _, outcome = start_apply_scanner_workflow(
            self.scanner, session_id, triggered_by_user_id=self.user.id, trigger=ObservationTrigger.ON_DEMAND
        )

        assert outcome is WorkflowStartOutcome.ALREADY_RUNNING
        assert pending_enqueue_claims_for_team(self.team.id) == expected_claims

    def test_stale_row_snapshot_self_corrects_after_claim(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A row count staler than the claim decay grace must not admit past the cap: the post-claim
        # validation re-reads rows with the claim already registered.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="already-running",
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.PENDING,
        )

        with (
            patch("products.replay_vision.backend.api.trigger.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1),
            patch("products.replay_vision.backend.enqueue_claims.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1),
        ):
            _, outcome = start_apply_scanner_workflow(
                self.scanner,
                "sess-stale",
                triggered_by_user_id=self.user.id,
                trigger=ObservationTrigger.ON_DEMAND,
                team_in_flight_rows=0,
                scanner_in_flight_rows=0,
            )

        assert outcome is WorkflowStartOutcome.CAPPED
        start_workflow.assert_not_called()

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
        self.assertEqual(kwargs["execution_timeout"], APPLY_SCANNER_EXECUTION_TIMEOUT)
        self.assertEqual(kwargs["priority"], on_demand_priority(self.team.id))
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

    def test_observe_returns_429_when_the_atomic_claim_is_refused(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The snapshot pre-check can pass while a racing request holds the last slot; the atomic claim
        # is the authoritative gate, so its refusal must surface as 429 and start no workflow.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        with patch("products.replay_vision.backend.api.trigger.try_claim_enqueue_slot", return_value=False):
            resp = self.client.post(
                self.observe_url(str(self.scanner.id)), data={"session_id": "sess-capped"}, format="json"
            )

        self.assertEqual(resp.status_code, 429, resp.json())
        start_workflow.assert_not_called()
        self.assertFalse(ReplayObservation.objects.filter(scanner=self.scanner, session_id="sess-capped").exists())

    def test_quota_blocked_observe_reports_exhaustion(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A quota-blocked 402 must still report the exhaustion event.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        exhausted = MagicMock(credit_limit=500, period_end=timezone.now())
        with patch("products.replay_vision.backend.api.trigger.quota_state", return_value=exhausted):
            with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
                resp = self.client.post(
                    self.observe_url(str(self.scanner.id)), data={"session_id": "sess-quota"}, format="json"
                )

        self.assertEqual(resp.status_code, 402, resp.json())
        report.assert_called_once()
        self.assertEqual(report.call_args.args[1], "replay_vision_quota_exhausted")
        self.assertEqual(report.call_args.args[2]["trigger"], "on_demand")

    def test_observe_is_refused_when_the_scanner_limit_is_reached(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=1)

        resp = self.client.post(self.observe_url(str(self.scanner.id)), data={"session_id": "sess-42"}, format="json")

        self.assertEqual(resp.status_code, 402, resp.json())
        self.assertIn("scanner", resp.json()["detail"].lower())
        mock_async_to_sync.assert_not_called()

    def test_observe_scanner_limit_does_not_report_org_quota_exhaustion(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A self-imposed per-scanner cap must never fire the org-exhaustion event: that metric means
        # "the org ran out of credits", not "this scanner hit the limit its owner chose".
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=1)

        with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
            resp = self.client.post(
                self.observe_url(str(self.scanner.id)), data={"session_id": "sess-42"}, format="json"
            )

        self.assertEqual(resp.status_code, 402, resp.json())
        report.assert_not_called()

    def test_observe_is_unaffected_when_no_scanner_limit_is_set(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        resp = self.client.post(self.observe_url(str(self.scanner.id)), data={"session_id": "sess-42"}, format="json")

        self.assertEqual(resp.status_code, 202, resp.json())


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
class TestBulkObserveAction(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def bulk_url(self, scanner_id: str) -> str:
        return f"{self.scanners_url}{scanner_id}/bulk_observe/"

    def _in_flight(self, session_id: str) -> None:
        ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.PENDING,
        )

    def test_starts_a_scan_per_session_and_reports_started(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["a", "b", "c"]}, format="json"
        )
        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 3)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "started", "started"])
        self.assertEqual(start_workflow.call_count, 3)

    def test_deduplicates_session_ids(self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock) -> None:
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["dup", "dup", "other"]}, format="json"
        )
        self.assertEqual(resp.status_code, 202, resp.json())
        # The repeated id collapses to one — a second start would be a wasted no-op.
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["dup", "other"])
        self.assertEqual(start_workflow.call_count, 2)

    def test_scans_what_fits_under_the_in_flight_cap_and_skips_the_rest(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        # Two slots already used against a cap of 3 → only one new scan fits; the other two are skipped.
        self._in_flight("running-1")
        self._in_flight("running-2")

        with patch("products.replay_vision.backend.scanning.MAX_IN_FLIGHT_APPLIES_PER_SCANNER", 3):
            resp = self.client.post(
                self.bulk_url(str(self.scanner.id)), data={"session_ids": ["x", "y", "z"]}, format="json"
            )
        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 1)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "skipped_limit", "skipped_limit"])

    def test_skips_for_quota_when_the_credit_budget_is_the_tighter_limit(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        # Enough in-flight headroom, but only one observation's worth of credits left → quota is the
        # binding limit, so the skip reason must say quota, not in-flight.
        cost = observation_credits_for_model(self.scanner.model)
        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", cost):
            with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
                resp = self.client.post(
                    self.bulk_url(str(self.scanner.id)), data={"session_ids": ["p", "q"]}, format="json"
                )
        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 1)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "skipped_quota"])
        events = [call.args[1] for call in report.call_args_list]
        self.assertEqual(events, ["replay_vision_bulk_scan_started", "replay_vision_quota_exhausted"])
        self.assertEqual(report.call_args.args[2]["trigger"], "bulk")

    def test_bulk_observe_reports_the_scanner_limit_as_the_skip_reason(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The scanner's own limit is tighter than the wide-open org and in-flight caps, so every
        # session must be skipped under the scanner-specific reason, not the generic quota one.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        cost = observation_credits_for_model(self.scanner.model)
        seed_scanner_spend(self.scanner, cost)
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=cost)

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["s-1", "s-2"]}, format="json"
        )

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 0)
        self.assertEqual({r["scan_outcome"] for r in body["results"]}, {"skipped_scanner_limit"})

    @parameterized.expand(
        [
            # Tied limits: the scanner limit names itself, since it's the one the user can raise.
            ("tied", 1, 1, "skipped_scanner_limit"),
            # Org limit strictly tighter than the scanner's own: the org quota is the binding reason.
            ("org_strictly_tighter", 2, 1, "skipped_quota"),
        ]
    )
    def test_bulk_observe_scanner_limit_tie_with_org_limit_wins_the_label(
        self,
        mock_sync_connect: MagicMock,
        mock_async_to_sync: MagicMock,
        _name: str,
        scanner_limit_multiplier: int,
        org_quota_multiplier: int,
        expected_outcome: str,
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        cost = observation_credits_for_model(self.scanner.model)
        seed_scanner_spend(self.scanner, cost)
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=cost * scanner_limit_multiplier)

        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", cost * org_quota_multiplier):
            resp = self.client.post(
                self.bulk_url(str(self.scanner.id)), data={"session_ids": ["s-1", "s-2"]}, format="json"
            )

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 0)
        self.assertEqual({r["scan_outcome"] for r in body["results"]}, {expected_outcome})

    def test_bulk_observe_scanner_limit_does_not_report_org_quota_exhaustion(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        cost = observation_credits_for_model(self.scanner.model)
        seed_scanner_spend(self.scanner, cost)
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=cost)

        with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
            resp = self.client.post(self.bulk_url(str(self.scanner.id)), data={"session_ids": ["s-1"]}, format="json")

        self.assertEqual(resp.status_code, 202, resp.json())
        events = [call.args[1] for call in report.call_args_list]
        self.assertEqual(events, ["replay_vision_bulk_scan_started"])

    def test_bulk_observe_partial_fit_starts_what_the_scanner_limit_affords(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Room for exactly two more observations and three sessions requested: the batch starts two
        # and labels the remainder with the scanner-specific reason.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        cost = observation_credits_for_model(self.scanner.model)
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(credit_limit=2 * cost)

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["p-1", "p-2", "p-3"]}, format="json"
        )

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 2)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "started", "skipped_scanner_limit"])

    def test_bulk_observe_is_unaffected_when_no_scanner_limit_is_set(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["a", "b", "c"]}, format="json"
        )

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 3)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "started", "started"])

    def test_quota_bound_batch_that_fits_does_not_report_exhaustion(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()

        def _start(*args: Any, **kwargs: Any) -> None:
            if kwargs["id"] == build_apply_scanner_workflow_id(self.scanner.id, "already"):
                raise WorkflowAlreadyStartedError(workflow_id=kwargs["id"], workflow_type=APPLY_SCANNER_WORKFLOW_NAME)

        mock_async_to_sync.return_value = MagicMock(side_effect=_start)
        # Claims left by earlier tests' mocked starts would shrink the in-flight headroom below the quota.
        get_client().delete(_team_key(self.team.id), _scanner_key(self.scanner.id))
        # Quota is the tighter limit, but the whole batch fits under it: one session is merely
        # already running, so no exhaustion should be reported.
        cost = observation_credits_for_model(self.scanner.model)
        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", 2 * cost):
            with patch("products.replay_vision.backend.api.scanners.report_user_action") as report:
                resp = self.client.post(
                    self.bulk_url(str(self.scanner.id)), data={"session_ids": ["already", "b"]}, format="json"
                )
        self.assertEqual(resp.status_code, 202, resp.json())
        self.assertEqual([r["scan_outcome"] for r in resp.json()["results"]], ["already_running", "started"])
        self.assertEqual([call.args[1] for call in report.call_args_list], ["replay_vision_bulk_scan_started"])

    def test_concurrent_claim_exhaustion_maps_to_skipped_limit(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The headroom pre-slice passed, but a racing request consumed the remaining slots before we
        # could start — the atomic claim refuses, and the result must read as the limit, not a failure.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        with patch(
            "products.replay_vision.backend.api.trigger.try_claim_enqueue_slot", side_effect=[True, False]
        ) as claim:
            resp = self.client.post(
                self.bulk_url(str(self.scanner.id)), data={"session_ids": ["a", "b", "c"]}, format="json"
            )

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 1)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["started", "skipped_limit", "skipped_limit"])
        # The refused claim short-circuits the batch; no third claim attempt is made.
        self.assertEqual(claim.call_count, 2)

    def test_already_running_session_is_a_no_op_and_consumes_no_headroom(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock()

        def _start(*args: Any, **kwargs: Any) -> None:
            # The first session is already running elsewhere; the rest start normally.
            if kwargs["id"] == build_apply_scanner_workflow_id(self.scanner.id, "already"):
                raise WorkflowAlreadyStartedError(workflow_id=kwargs["id"], workflow_type=APPLY_SCANNER_WORKFLOW_NAME)

        mock_async_to_sync.return_value = MagicMock(side_effect=_start)

        resp = self.client.post(
            self.bulk_url(str(self.scanner.id)), data={"session_ids": ["already", "fresh"]}, format="json"
        )
        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["started"], 1)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["already_running", "started"])

    def test_rejects_empty_and_oversized_batches(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        empty = self.client.post(self.bulk_url(str(self.scanner.id)), data={"session_ids": []}, format="json")
        self.assertEqual(empty.status_code, 400)
        too_many = self.client.post(
            self.bulk_url(str(self.scanner.id)),
            data={"session_ids": [f"s{i}" for i in range(201)]},
            format="json",
        )
        self.assertEqual(too_many.status_code, 400)


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
        self.assertEqual(inputs.triggered_by, ObservationTrigger.RETRY)
        self.assertEqual(inputs.triggered_by_user_id, self.user.id)

    def test_retry_accepts_ineligible_observation(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Ineligibility can be a timing artifact (snapshots that finished ingesting after the scan), and the
        # UNIQUE(scanner, session_id) row would otherwise lock the session out of this scanner forever.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="sess-ineligible",
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.INELIGIBLE,
            error_reason="no_snapshots:No snapshots after processing",
            completed_at=timezone.now(),
        )

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 202, resp.json())
        self.assertFalse(ReplayObservation.objects.filter(id=observation.id).exists())
        args, _kwargs = start_workflow.call_args
        self.assertEqual(args[1].triggered_by, ObservationTrigger.RETRY)

    def test_retry_keeps_row_when_ai_consent_is_off(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The replacement workflow fails closed at create time when consent is off, so letting the retry
        # delete the row first would leave the recording looking unscanned with no way to get a row back.
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-no-consent")
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
        start_workflow.assert_not_called()

    def test_retry_reports_status_before_consent(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Both paths 400, so only the message distinguishes them. A succeeded observation should hear
        # that it isn't retryable, not that the org needs to turn on AI.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        observation = self._create_failed("sess-order")
        ReplayObservation.objects.filter(id=observation.id).update(status=ObservationStatus.SUCCEEDED)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        resp = self.client.post(self.retry_url(str(observation.id)))

        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertIn("retried", resp.json()["detail"])

    def test_retry_rejects_non_terminal_statuses(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Plain loop, not @parameterized: class-level @patch mis-orders expanded args.
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        cases = [
            (ObservationStatus.SUCCEEDED, timezone.now()),
            (ObservationStatus.PENDING, None),
            (ObservationStatus.RUNNING, None),
        ]
        for status_value, completed_at in cases:
            with self.subTest(status=status_value):
                observation = ReplayObservation.objects.create(
                    scanner=self.scanner,
                    session_id=f"sess-keep-{status_value}",
                    scanner_snapshot=_snapshot_for(self.scanner),
                    triggered_by=ObservationTrigger.SCHEDULE,
                    status=status_value,
                    error_reason="",
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
        with patch("products.replay_vision.backend.api.trigger.quota_state", return_value=exhausted):
            resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 402, resp.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
        start_workflow.assert_not_called()

    def test_retry_keeps_row_when_the_scanners_own_limit_is_reached(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Retry deletes the failed row before dispatching; without this gate the refused replacement
        # leaves the row gone while the caller is told the retry started.
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-scanner-limit")
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(
            credit_limit=observation_credits_for_model(self.scanner.model) - 1
        )

        resp = self.client.post(self.retry_url(str(observation.id)))

        self.assertEqual(resp.status_code, 402, resp.json())
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())
        start_workflow.assert_not_called()

    def test_retry_dispatch_failure_returns_503_with_row_and_label_restored(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The replacement run never started, so the failed row must come back instead of leaving the
        # recording looking unscanned while the usage ledger still counts the failed attempt. The delete
        # cascades the shared rating away, so restoring only the row silently loses the team's feedback
        # while the response claims the observation was kept.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock(side_effect=RuntimeError("temporal unavailable"))
        observation = self._create_failed("sess-broken")
        original_created_at = observation.created_at
        label = ReplayObservationLabel.objects.create(
            observation=observation, team=self.team, is_correct=False, feedback="missed the error banner"
        )

        resp = self.client.post(self.retry_url(str(observation.id)))
        self.assertEqual(resp.status_code, 503)
        # `detail` is what the frontend toast surfaces; `error` would be silently dropped.
        self.assertIn("was kept", resp.json()["detail"])
        restored = ReplayObservation.objects.get(id=observation.id)
        self.assertEqual(restored.status, ObservationStatus.FAILED)
        self.assertEqual(restored.created_at, original_created_at)
        restored_label = ReplayObservationLabel.objects.get(observation_id=observation.id)
        self.assertEqual(restored_label.id, label.id)
        self.assertFalse(restored_label.is_correct)
        self.assertEqual(restored_label.feedback, "missed the error banner")
        self.assertEqual(restored_label.created_at, label.created_at)

    def test_retry_returns_429_and_keeps_row_and_label_when_the_atomic_claim_is_refused(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The claim can refuse after the snapshot pre-check passed. Claiming before the delete keeps a
        # capped retry a pure no-op: deleting first would cascade away the team's rating on a request
        # that changes nothing.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        observation = self._create_failed("sess-capped")
        original_created_at = observation.created_at
        ReplayObservationLabel.objects.create(
            observation=observation, team=self.team, is_correct=False, feedback="missed the error banner"
        )

        with patch("products.replay_vision.backend.api.trigger.try_claim_enqueue_slot", return_value=False):
            resp = self.client.post(self.retry_url(str(observation.id)))

        self.assertEqual(resp.status_code, 429, resp.json())
        start_workflow.assert_not_called()
        restored = ReplayObservation.objects.get(id=observation.id)
        self.assertEqual(restored.status, ObservationStatus.FAILED)
        self.assertEqual(restored.created_at, original_created_at)
        self.assertEqual(
            ReplayObservationLabel.objects.get(observation_id=observation.id).feedback, "missed the error banner"
        )

    def test_retry_reports_409_when_the_replacement_run_already_holds_the_session(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A start we couldn't confirm may still have persisted its own row for this (scanner, session).
        # Restoring on top of it violates the unique constraint, which used to surface as a 500.
        observation = self._create_failed("sess-raced")

        def start_and_take_the_slot(*args, **kwargs):
            ReplayObservation.objects.create(
                scanner=self.scanner,
                session_id="sess-raced",
                scanner_snapshot=_snapshot_for(self.scanner),
                triggered_by=ObservationTrigger.RETRY,
                status=ObservationStatus.PENDING,
            )
            raise RuntimeError("temporal unavailable")

        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock(side_effect=start_and_take_the_slot)

        resp = self.client.post(self.retry_url(str(observation.id)))

        self.assertEqual(resp.status_code, 409, resp.json())
        self.assertIn("still finishing", resp.json()["detail"])
        self.assertEqual(ReplayObservation.objects.filter(scanner=self.scanner, session_id="sess-raced").count(), 1)

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
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_object",
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
        # The restart was blocked, so the failed row is restored and the retry can be attempted again.
        self.assertTrue(ReplayObservation.objects.filter(id=observation.id).exists())

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
            model=ScannerModel.GEMINI_3_7_FLASH,
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

    def test_retrieve_neighbors_honor_list_filters(self) -> None:
        now = timezone.now()
        old = self._create_observation(self.scanner_a, "s-old")
        failed = self._create_observation(self.scanner_a, "s-failed")
        new = self._create_observation(self.scanner_a, "s-new")
        ReplayObservation.objects.filter(pk=old.id).update(
            created_at=now - timedelta(minutes=2), status=ObservationStatus.SUCCEEDED, completed_at=now
        )
        ReplayObservation.objects.filter(pk=failed.id).update(
            created_at=now - timedelta(minutes=1),
            status=ObservationStatus.FAILED,
            completed_at=now,
            error_reason="boom",
        )
        ReplayObservation.objects.filter(pk=new.id).update(
            created_at=now, status=ObservationStatus.SUCCEEDED, completed_at=now
        )

        unfiltered = self.client.get(f"{self.session_observations_url}{new.id}/").json()
        self.assertEqual(unfiltered["next_observation_id"], str(failed.id))

        filtered = self.client.get(f"{self.session_observations_url}{new.id}/?status=succeeded").json()
        self.assertEqual(filtered["next_observation_id"], str(old.id))
        self.assertIsNone(filtered["previous_observation_id"])

    def test_retrieve_neighbors_honor_score_bounds(self) -> None:
        scorer = self._create_scanner(
            name="frustration",
            scanner_type=ScannerType.SCORER,
            scanner_config={"prompt": "p", "scale": {"min": 0, "max": 10}},
        )
        now = timezone.now()
        ids = []
        # created_at ascends with idx, so the default -created_at listing is sess-2, sess-1, sess-0.
        for idx, score in enumerate([9.0, 2.0, 8.0]):
            obs = self._create_observation(scorer, f"sess-{idx}")
            ReplayObservation.objects.filter(pk=obs.id).update(
                created_at=now - timedelta(minutes=2 - idx),
                status=ObservationStatus.SUCCEEDED,
                completed_at=now,
                scanner_result={
                    "model_output": {"scanner_type": "scorer", "score": score, "reasoning": "r", "confidence": 0.5},
                    "signals_count": 0,
                },
            )
            ids.append(obs.id)

        unfiltered = self.client.get(f"{self.session_observations_url}{ids[2]}/").json()
        self.assertEqual(unfiltered["next_observation_id"], str(ids[1]))

        # min_score=7 drops the 2.0 row, so next skips to the 9.0 row.
        filtered = self.client.get(f"{self.session_observations_url}{ids[2]}/?min_score=7").json()
        self.assertEqual(filtered["next_observation_id"], str(ids[0]))
        self.assertIsNone(filtered["previous_observation_id"])

    def test_retrieve_neighbors_honor_order_by(self) -> None:
        now = timezone.now()
        old = self._create_observation(self.scanner_a, "s-old")
        mid = self._create_observation(self.scanner_a, "s-mid")
        new = self._create_observation(self.scanner_a, "s-new")
        ReplayObservation.objects.filter(pk=old.id).update(created_at=now - timedelta(minutes=2))
        ReplayObservation.objects.filter(pk=mid.id).update(created_at=now - timedelta(minutes=1))
        ReplayObservation.objects.filter(pk=new.id).update(created_at=now)

        # Ascending created_at reverses the list, so prev/next flip relative to the default ordering.
        body = self.client.get(f"{self.session_observations_url}{mid.id}/?order_by=created_at").json()
        self.assertEqual(body["previous_observation_id"], str(old.id))
        self.assertEqual(body["next_observation_id"], str(new.id))

    def test_retrieve_neighbors_empty_when_observation_outside_filtered_set(self) -> None:
        observation = self._create_observation(self.scanner_a, "s-pending")
        self._create_observation(self.scanner_a, "s-sibling")

        body = self.client.get(f"{self.session_observations_url}{observation.id}/?status=succeeded").json()
        self.assertIsNone(body["previous_observation_id"])
        self.assertIsNone(body["next_observation_id"])


class TestObservationSearchAction(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner(name="searchable")

    @property
    def search_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/observations/search/"

    def _create_succeeded_observation(self, session_id: str, scanner: ReplayScanner | None = None) -> ReplayObservation:
        scanner = scanner or self.scanner
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        ReplayObservation.objects.filter(pk=observation.id).update(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()
        )
        return observation

    @parameterized.expand(
        [
            ("missing_q", ""),
            ("limit_above_cap", "?q=checkout&limit=51"),
            ("unknown_verdict", "?q=checkout&verdict=yes,maybe"),
            ("min_score_above_max_score", "?q=checkout&min_score=5&max_score=1"),
            ("nan_score", "?q=checkout&min_score=nan"),
            ("infinite_score", "?q=checkout&max_score=inf"),
        ]
    )
    def test_search_rejects_bad_params(self, _name: str, query_string: str) -> None:
        resp = self.client.get(f"{self.search_url}{query_string}")
        self.assertEqual(resp.status_code, 400)

    @patch("products.replay_vision.backend.api.observations.rank_observations")
    @patch("products.replay_vision.backend.api.observations.generate_embedding")
    def test_search_returns_results_in_rank_order(self, mock_embed: MagicMock, mock_rank: MagicMock) -> None:
        first = self._create_succeeded_observation("sess-1")
        second = self._create_succeeded_observation("sess-2")
        mock_embed.return_value = MagicMock(embedding=[0.1, 0.2])
        # A ranked id with no readable row must be skipped, not 500 or leak.
        mock_rank.return_value = [
            ObservationMatch(observation_id=str(second.id), distance=0.1, matched_content="user rage-clicked"),
            ObservationMatch(observation_id=str(uuid7()), distance=0.2, matched_content=""),
            ObservationMatch(observation_id=str(first.id), distance=0.3, matched_content=""),
        ]

        resp = self.client.get(f"{self.search_url}?q=confused users")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(
            [(r["observation"]["id"], r["distance"], r["matched_content"]) for r in resp.json()["results"]],
            [(str(second.id), 0.1, "user rage-clicked"), (str(first.id), 0.3, "")],
        )
        self.assertFalse(resp.json()["truncated"])

    @patch("products.replay_vision.backend.api.observations.rank_observations")
    @patch("products.replay_vision.backend.api.observations.generate_embedding")
    def test_search_overfetches_then_slices_to_limit_and_flags_truncation(
        self, mock_embed: MagicMock, mock_rank: MagicMock
    ) -> None:
        first = self._create_succeeded_observation("sess-1")
        second = self._create_succeeded_observation("sess-2")
        mock_embed.return_value = MagicMock(embedding=[0.1])
        # The best-ranked id hydrates to nothing readable; the over-fetched tail must fill the response
        # up to `limit`, and the extra readable row must be cut, not returned.
        mock_rank.return_value = [
            ObservationMatch(observation_id=str(uuid7()), distance=0.1, matched_content=""),
            ObservationMatch(observation_id=str(first.id), distance=0.2, matched_content=""),
            ObservationMatch(observation_id=str(second.id), distance=0.3, matched_content=""),
        ]

        resp = self.client.get(f"{self.search_url}?q=confused users&limit=1")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertGreater(mock_rank.call_args[0][4], 1)
        self.assertEqual([r["observation"]["id"] for r in resp.json()["results"]], [str(first.id)])
        self.assertTrue(resp.json()["truncated"])

    @patch("products.replay_vision.backend.api.observations.rank_observations")
    @patch("products.replay_vision.backend.api.observations.generate_embedding")
    def test_search_drops_rows_whose_snapshot_experiment_is_restricted(
        self, mock_embed: MagicMock, mock_rank: MagicMock
    ) -> None:
        experiment = create_experiment(self.team, "restricted-flag")
        targeted = self._create_scanner(
            name="was-targeted", experiment_targeting={"experiment_id": experiment.id, "variant": "test"}
        )
        restricted = self._create_succeeded_observation("sess-restricted", scanner=targeted)
        # Clear the targeting so the scanner passes the scanner gate. The row's snapshot must still block it.
        targeted.experiment_targeting = None
        targeted.save(update_fields=["experiment_targeting"])
        visible = self._create_succeeded_observation("sess-visible")
        mock_embed.return_value = MagicMock(embedding=[0.1])
        mock_rank.return_value = [
            ObservationMatch(observation_id=str(restricted.id), distance=0.1, matched_content=""),
            ObservationMatch(observation_id=str(visible.id), distance=0.2, matched_content=""),
        ]

        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=experiment.pk) if qs.model is Experiment else qs,
        ):
            resp = self.client.get(f"{self.search_url}?q=anything")

        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([r["observation"]["id"] for r in resp.json()["results"]], [str(visible.id)])

    @patch("products.replay_vision.backend.api.observations.rank_observations", return_value=[])
    @patch("products.replay_vision.backend.api.observations.generate_embedding")
    def test_search_hides_scanner_targeting_a_restricted_experiment(
        self, mock_embed: MagicMock, mock_rank: MagicMock
    ) -> None:
        experiment = create_experiment(self.team, "restricted-flag")
        denied = self._create_scanner(
            name="targeted", experiment_targeting={"experiment_id": experiment.id, "variant": "test"}
        )
        mock_embed.return_value = MagicMock(embedding=[0.1])

        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=experiment.pk) if qs.model is Experiment else qs,
        ):
            scoped = self.client.get(f"{self.search_url}?q=anything&scanner_id={denied.id}")
            cross = self.client.get(f"{self.search_url}?q=anything")

        # Not-found rather than 403, so the response never leaks the experiment's existence.
        self.assertEqual(scoped.status_code, 404)
        self.assertEqual(cross.status_code, 200)
        searched_scanner_ids = mock_rank.call_args[0][2]
        self.assertNotIn(str(denied.id), searched_scanner_ids)
        self.assertIn(str(self.scanner.id), searched_scanner_ids)

    # `generate_embedding` posts through a `requests` session, so its transport failures are the
    # `requests` exceptions — an `httpx` mock here would exercise a handler that can never fire.
    @parameterized.expand(
        [
            ("unreachable", requests.ConnectionError),
            ("slow", requests.Timeout),
        ]
    )
    def test_search_returns_503_when_embedding_unavailable(self, _name: str, exception_class: type) -> None:
        with patch(
            "products.replay_vision.backend.api.observations.generate_embedding",
            side_effect=exception_class("embedding service down"),
        ):
            resp = self.client.get(f"{self.search_url}?q=anything")
        self.assertEqual(resp.status_code, 503)

    @patch("products.replay_vision.backend.api.observations.is_ai_data_processing_approved", return_value=False)
    def test_search_returns_400_when_ai_consent_is_off(self, _mock_consent: MagicMock) -> None:
        resp = self.client.get(f"{self.search_url}?q=anything")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("allow AI analysis", resp.json()["detail"])

    def test_search_with_unknown_scanner_returns_404(self) -> None:
        resp = self.client.get(f"{self.search_url}?q=anything&scanner_id={uuid7()}")
        self.assertEqual(resp.status_code, 404)

    # Guards the wiring, not the rate: the action-level `throttle_classes` must actually reach
    # `get_throttles()`, or the endpoint ships with no throttle at all.
    @patch("posthog.rate_limit.ReplayVisionSearchBurstRateThrottle.rate", new="2/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.replay_vision.backend.api.observations.rank_observations", return_value=[])
    @patch("products.replay_vision.backend.api.observations.generate_embedding")
    def test_search_is_rate_limited(
        self, mock_embed: MagicMock, _mock_rank: MagicMock, _mock_enabled: MagicMock
    ) -> None:
        cache.clear()
        mock_embed.return_value = MagicMock(embedding=[0.1])
        for _ in range(2):
            self.assertEqual(self.client.get(f"{self.search_url}?q=anything").status_code, 200)

        self.assertEqual(self.client.get(f"{self.search_url}?q=anything").status_code, 429)


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
        # Inside the earliest probe but outside the 7-day scan window, clamping window_days to a deterministic 7.
        self._ingest_session(days_ago=7)

        resp = self.client.post(self.estimate_url, data={}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["matched_sessions_in_window"], 3)
        self.assertEqual(body["window_days"], 7)
        self.assertEqual(body["estimated_observations_per_month"], round(3 / 7 * 30))
        # Defaults to gemini-3-flash-preview (5 credits) when the request names no model.
        self.assertEqual(body["credits_per_observation"], 5)
        self.assertEqual(body["estimated_credits_per_month"], round(3 / 7 * 30) * 5)

    def test_estimate_prices_credits_at_proposed_model(self) -> None:
        for index in range(3):
            self._ingest_session(days_ago=index + 1)
        self._ingest_session(days_ago=40)

        resp = self.client.post(self.estimate_url, data={"model": "gemini-3.5-flash-lite"}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["credits_per_observation"], 2)
        self.assertEqual(body["estimated_credits_per_month"], body["estimated_observations_per_month"] * 2)

    def test_estimate_applies_sampling(self) -> None:
        for index in range(4):
            self._ingest_session(days_ago=index + 1)
        # Inside the earliest probe but outside the 7-day scan window, clamping window_days to a deterministic 7.
        self._ingest_session(days_ago=7)

        resp = self.client.post(self.estimate_url, data={"sampling_rate": 0.5}, format="json")
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body["matched_sessions_in_window"], 4)
        self.assertEqual(body["window_days"], 7)
        self.assertEqual(body["sampling_rate"], 0.5)
        self.assertEqual(body["estimated_observations_per_month"], round(4 / 7 * 30 * 0.5))

    def test_estimate_others_sum_is_enabled_only_and_excludes_the_edited_scanner(self) -> None:
        self._ingest_session(days_ago=1)

        def make(name: str, *, enabled: bool, estimate: int) -> ReplayScanner:
            return ReplayScanner.objects.create(
                team=self.team,
                name=name,
                scanner_type=ScannerType.MONITOR,
                scanner_config={"prompt": "p"},
                model=ScannerModel.GEMINI_3_7_FLASH,
                enabled=enabled,
                estimated_monthly_observations=estimate,
            )

        a = make("a", enabled=True, estimate=100)
        make("b", enabled=True, estimate=250)
        make("disabled", enabled=False, estimate=999)  # disabled scanners don't count

        # New scanner (no scanner_id): others = both enabled scanners, credit-weighted at 15/observation.
        new_body = self.client.post(self.estimate_url, data={}, format="json").json()
        self.assertEqual(new_body["other_enabled_scanners_monthly_credits"], 350 * 15)

        # Editing scanner `a`: its own stored estimate is excluded so the forecast won't double-count it.
        edit_body = self.client.post(self.estimate_url, data={"scanner_id": str(a.id)}, format="json").json()
        self.assertEqual(edit_body["other_enabled_scanners_monthly_credits"], 250 * 15)

    def test_estimate_reports_active_backfill_commitment(self) -> None:
        # The editor replaces the fleet total with `others + this scanner`, which drops the backfill credits the
        # quota snapshot carries. Without this field the forecast understates period-end spend while one runs.
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="backfilled",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        ReplayScannerBackfill.objects.for_team(self.team.id).create(
            scanner=scanner,
            team=self.team,
            window_start=timezone.now() - timedelta(days=5),
            window_end=timezone.now(),
            scanner_snapshot={},
            credits_per_observation=5,
            total_count=100,
            dispatched_count=40,
        )

        body = self.client.post(self.estimate_url, data={}, format="json").json()

        assert body["active_backfill_credits"] == 60 * 5

    def test_estimate_reports_no_backfill_commitment_when_none_are_active(self) -> None:
        body = self.client.post(self.estimate_url, data={}, format="json").json()
        assert body["active_backfill_credits"] == 0

    def test_estimate_rejects_scanner_id_outside_the_request_team(self) -> None:
        # A scanner_id from another team (even same org) must be rejected, not silently excluded from the others-sum.
        other_team = Team.objects.create(organization=self.team.organization, name="sibling")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="theirs",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
            enabled=True,
            estimated_monthly_observations=500,
        )
        resp = self.client.post(self.estimate_url, data={"scanner_id": str(other_scanner.id)}, format="json")
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_id")


class TestScannerSpend(_VisionAPITestCase):
    def _succeeded_observation(self, scanner: ReplayScanner, session_id: str, created_at=None) -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
        )
        if created_at is not None:
            ReplayObservation.objects.filter(pk=observation.pk).update(created_at=created_at)
        return observation

    def _credits_by_name(self, response_json: dict) -> dict[str, int]:
        return {row["name"]: row["credits_this_month"] for row in response_json["results"]}

    def test_credits_this_month_sums_current_period_succeeded_observations(self) -> None:
        spender = self._create_scanner(name="spender")
        self._create_scanner(name="idle")
        self._succeeded_observation(spender, "in-window-1")
        self._succeeded_observation(spender, "in-window-2")
        ReplayObservation.objects.create(
            scanner=spender,
            session_id="failed-in-window",
            scanner_snapshot=_snapshot_for(spender),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.FAILED,
            completed_at=timezone.now(),
        )
        self._succeeded_observation(spender, "last-period", created_at=timezone.now() - timedelta(days=45))

        resp = self.client.get(self.scanners_url)
        self.assertEqual(resp.status_code, 200, resp.json())
        credits = self._credits_by_name(resp.json())
        self.assertEqual(credits["spender"], 2 * observation_credits_for_model(spender.model))
        self.assertEqual(credits["idle"], 0)

    def test_order_by_credits_matches_displayed_values(self) -> None:
        low = self._create_scanner(name="low")
        high = self._create_scanner(name="high")
        self._succeeded_observation(low, "low-1")
        for i in range(3):
            self._succeeded_observation(high, f"high-{i}")

        resp = self.client.get(f"{self.scanners_url}?order_by=-credits_this_month")
        self.assertEqual(resp.status_code, 200, resp.json())
        rows = resp.json()["results"]
        displayed = [row["credits_this_month"] for row in rows]
        self.assertEqual(displayed, sorted(displayed, reverse=True))
        self.assertEqual([row["name"] for row in rows[:2]], ["high", "low"])

    def test_receipts_without_a_scanner_do_not_zero_the_displayed_credits(self) -> None:
        # Receipts are never backfilled with a scanner_id, so the displayed column and its sort read
        # observation rows. Pointing either at the ledger silently zeroes both for a whole period.
        spender = self._create_scanner(name="spender")
        observation = self._succeeded_observation(spender, "unattributed")
        ReplayObservationUsage.objects.create(
            observation_id=observation.id,
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
            scanner_id=None,
            observation_created_at=observation.created_at,
            model=spender.model,
            credits=observation_credits_for_model(spender.model),
        )

        resp = self.client.get(f"{self.scanners_url}?order_by=-credits_this_month")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(self._credits_by_name(resp.json())["spender"], observation_credits_for_model(spender.model))

    def _spend_against_limit(self, scanner: ReplayScanner, session_id: str) -> None:
        """Ledger spend, which is what the limit is enforced on. `_succeeded_observation` deliberately
        writes no receipt, because it seeds the displayed column, which reads observation rows."""
        observation = self._succeeded_observation(scanner, session_id)
        ReplayObservationUsage.objects.create(
            observation_id=observation.id,
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
            scanner_id=scanner.id,
            observation_created_at=observation.created_at,
            model=scanner.model,
            credits=observation_credits_for_model(scanner.model),
        )

    def test_limit_reached_is_reported_per_scanner(self) -> None:
        scanner = self._create_scanner()
        cost = observation_credits_for_model(scanner.model)
        ReplayScanner.objects.filter(pk=scanner.pk).update(credit_limit=cost)

        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertIs(resp.json()["limit_reached"], False)

        self._spend_against_limit(scanner, "over-limit")

        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertIs(resp.json()["limit_reached"], True)
        self.assertEqual(resp.json()["credits_used_against_limit"], cost)

    def test_limit_fields_are_per_row_on_the_list_endpoint(self) -> None:
        # The page's budgets are computed once and cached on the shared serializer context, so a lookup
        # keyed on the wrong scanner would give every row the first row's answer.
        capped = self._create_scanner(name="capped")
        self._create_scanner(name="uncapped")
        cost = observation_credits_for_model(capped.model)
        ReplayScanner.objects.filter(pk=capped.pk).update(credit_limit=cost)
        self._spend_against_limit(capped, "capped-spend")

        resp = self.client.get(self.scanners_url)
        self.assertEqual(resp.status_code, 200, resp.json())
        by_name = {row["name"]: row for row in resp.json()["results"]}
        self.assertIs(by_name["capped"]["limit_reached"], True)
        self.assertIs(by_name["uncapped"]["limit_reached"], False)
        self.assertEqual(by_name["capped"]["credits_used_against_limit"], cost)
        self.assertEqual(by_name["uncapped"]["credits_used_against_limit"], 0)

    def test_limit_below_one_observation_reports_reached_before_any_spend(self) -> None:
        # `limit_reached` answers "can this scanner run again", not "has it spent its limit". A cap
        # smaller than one observation blocks the scanner immediately, and the UI must say so.
        scanner = self._create_scanner()
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            credit_limit=observation_credits_for_model(scanner.model) - 1
        )

        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertIs(resp.json()["limit_reached"], True)
        self.assertEqual(resp.json()["credits_used_against_limit"], 0)

    def test_list_endpoint_query_count_does_not_scale_with_page_size(self) -> None:
        # Both spend figures are computed once per page and cached on the shared serializer context.
        # Asserting the count rather than matching SQL text keeps this from breaking on a query refactor
        # that preserves the property, and from passing on an N+1 that happens to be shaped differently.
        one = self._create_scanner(name="scanner-0")
        ReplayScanner.objects.filter(pk=one.pk).update(credit_limit=10_000)
        self._spend_against_limit(one, "seed-0")
        with CaptureQueriesContext(connection) as single_page:
            self.assertEqual(self.client.get(self.scanners_url).status_code, 200)

        for i in range(1, 5):
            extra = self._create_scanner(name=f"scanner-{i}")
            ReplayScanner.objects.filter(pk=extra.pk).update(credit_limit=10_000)
            self._spend_against_limit(extra, f"seed-{i}")
        with CaptureQueriesContext(connection) as five_page:
            self.assertEqual(self.client.get(self.scanners_url).status_code, 200)

        # Only the spend sources are asserted. Other parts of the endpoint may legitimately do per-row
        # work, and matching on table name survives a query refactor that keeps the property.
        def spend_queries(ctx: CaptureQueriesContext) -> int:
            return len([q for q in ctx.captured_queries if "replay_vision_replayobservation" in q["sql"]])

        self.assertEqual(spend_queries(five_page), spend_queries(single_page))


class TestCurrentPeriodBounds(SimpleTestCase):
    NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    MONTH_BOUNDS = (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC))

    @parameterized.expand(
        [
            ("no_organization", None, MONTH_BOUNDS),
            ("no_usage", {}, MONTH_BOUNDS),
            (
                "current_billing_period",
                {"period": ["2026-07-10T00:00:00+00:00", "2026-08-10T00:00:00+00:00"]},
                (datetime(2026, 7, 10, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC)),
            ),
            (
                "stale_billing_period_falls_back_to_month",
                {"period": ["2026-05-10T00:00:00+00:00", "2026-06-10T00:00:00+00:00"]},
                MONTH_BOUNDS,
            ),
            (
                "naive_timestamps_treated_as_utc",
                {"period": ["2026-07-10T00:00:00", "2026-08-10T00:00:00"]},
                (datetime(2026, 7, 10, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC)),
            ),
        ]
    )
    def test_period_selection(self, _name: str, usage: dict | None, expected: tuple[datetime, datetime]) -> None:
        organization = Organization(usage=usage) if usage is not None else None
        self.assertEqual(_current_period_bounds(organization, self.NOW), BillingPeriod(*expected))


class TestScannerCreditLimitValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("null_is_allowed", None, True),
            ("one_is_allowed", 1, True),
            ("large_is_allowed", 1_000_000, True),
            ("int4_max_is_allowed", 2_147_483_647, True),
            ("zero_is_rejected", 0, False),
            ("negative_is_rejected", -1, False),
            ("over_int4_is_rejected", 2_147_483_648, False),
        ]
    )
    def test_credit_limit_bounds(self, _name: str, limit: int | None, expected_valid: bool) -> None:
        serializer = ReplayScannerSerializer(data={"credit_limit": limit}, partial=True)
        self.assertIs(serializer.is_valid(), expected_valid)
        if not expected_valid:
            self.assertIn("credit_limit", serializer.errors)


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
class TestInlineScanAction(_VisionAPITestCase):
    @property
    def inline_url(self) -> str:
        return f"{self.scanners_url}inline_scan/"

    def _payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"session_ids": ["sess-1"], "prompt": "did the user rage click?"}
        payload.update(overrides)
        return payload

    def _scan(self, **overrides: Any):
        return self.client.post(self.inline_url, data=self._payload(**overrides), format="json")

    def _finished_observation(self, scan_id: str, session_id: str) -> ReplayObservation:
        # The create activity runs in Temporal, which these tests mock out, so stand the row up directly.
        scanner = ReplayScanner.all_origins.get(id=scan_id)
        return ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
        )

    def test_same_prompt_reuses_one_scan_and_a_different_prompt_gets_its_own(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The whole point of keying on the config: re-asking must not mint a second scanner (and so a
        # second copy of every observation), while a different question must not land in the first's results.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        first = self._scan()
        again = self._scan(session_ids=["sess-2"])
        other = self._scan(prompt="did the user rage click twice?")

        self.assertEqual(first.json()["scan_id"], again.json()["scan_id"])
        self.assertNotEqual(first.json()["scan_id"], other.json()["scan_id"])
        self.assertEqual(ReplayScanner.all_origins.filter(origin=ScannerOrigin.INLINE).count(), 2)

    def test_a_scan_id_cannot_be_edited_as_a_scanner(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # An editable inline scanner is two bugs: PATCHing scanner_config leaves inline_key pointing at the
        # old config, and PATCHing enabled turns a row with an empty query into a sweep over every recording.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        scan_id = self._scan().json()["scan_id"]

        for payload in ({"scanner_config": {"prompt": "something else"}}, {"enabled": True, "sampling_rate": 0.5}):
            resp = self.client.patch(f"{self.scanners_url}{scan_id}/", data=payload, format="json")
            self.assertEqual(resp.status_code, 404, resp.content)

        scanner = ReplayScanner.all_origins.get(id=scan_id)
        self.assertFalse(scanner.enabled)
        self.assertEqual(scanner.scanner_config, {"prompt": "did the user rage click?"})

    def test_scans_stay_out_of_the_teams_scanner_surfaces(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A scan is not a scanner the team configured, so it must not show up where they're presented or
        # counted — including the usage report, which counts through the same default manager.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        configured = self._create_scanner()
        scan_id = self._scan().json()["scan_id"]

        listed = self.client.get(self.scanners_url).json()["results"]
        self.assertEqual([r["id"] for r in listed], [str(configured.id)])
        self.assertNotIn(scan_id, [r["id"] for r in listed])
        self.assertEqual(self.client.get(f"{self.scanners_url}stats/").json()["total"], 1)

    def test_a_used_up_quota_starts_nothing_and_leaves_no_scanner_behind(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # Minting before checking headroom means an org over quota accumulates a permanent row per
        # question it was never able to answer.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow

        with patch("products.replay_vision.backend.quota.MONTHLY_CREDIT_QUOTA", 0):
            resp = self._scan(session_ids=["sess-1", "sess-2"])

        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertIsNone(body["scan_id"])
        self.assertEqual(body["started"], 0)
        self.assertEqual([r["scan_outcome"] for r in body["results"]], ["skipped_quota", "skipped_quota"])
        self.assertFalse(ReplayScanner.all_origins.filter(origin=ScannerOrigin.INLINE).exists())
        start_workflow.assert_not_called()

    def test_a_finished_session_reports_already_scanned_without_starting_a_workflow(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # A terminal row makes (scanner, session) permanently taken, so starting a workflow would burn a
        # run only to lose the INSERT and hand back the row we can already see.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock(return_value=MagicMock())
        mock_async_to_sync.return_value = start_workflow
        scan_id = self._scan().json()["scan_id"]
        self._finished_observation(scan_id, "sess-1")
        start_workflow.reset_mock()

        resp = self._scan(session_ids=["sess-1", "sess-3"])

        outcomes = {r["session_id"]: r["scan_outcome"] for r in resp.json()["results"]}
        self.assertEqual(outcomes["sess-1"], "already_scanned")
        self.assertEqual(outcomes["sess-3"], "started")
        self.assertEqual(start_workflow.call_count, 1)

    def test_results_are_readable_through_the_scan_id(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        # The observations endpoint is the only way back to an inline scan's output, so it has to resolve
        # a scanner the scanner endpoints deliberately refuse to.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        scan_id = self._scan().json()["scan_id"]
        self._finished_observation(scan_id, "sess-1")

        resp = self.client.get(self.observations_url(scan_id))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([r["session_id"] for r in resp.json()["results"]], ["sess-1"])

    def test_requires_ai_consent(self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock) -> None:
        # New call site into the LLM path, so it needs its own consent gate rather than inheriting one.
        mock_sync_connect.return_value = MagicMock()
        start_workflow = MagicMock()
        mock_async_to_sync.return_value = start_workflow
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        resp = self._scan()

        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(ReplayScanner.all_origins.filter(origin=ScannerOrigin.INLINE).exists())
        start_workflow.assert_not_called()


class TestScannerSelfDrivingStatsAPI(_VisionAPITestCase):
    def test_returns_the_scanners_signal_outcomes(self) -> None:
        # Wiring guard: the endpoint must query the signals facade for this scanner's slice and
        # serialize the outcome counts; a dropped extra filter would return team-wide numbers.
        scanner = self._create_scanner()
        outcomes = SignalSourceSliceOutcomes(signal_count=5, report_count=2, pr_count=1, merged_pr_count=1)
        with patch(
            "products.replay_vision.backend.api.scanners.get_outcomes_for_signal_source_slice",
            return_value=outcomes,
        ) as mock_outcomes:
            response = self.client.get(f"{self.scanners_url}{scanner.id}/self_driving_stats/")

        assert response.status_code == 200
        assert response.json() == {
            "signals_emitted": 5,
            "reports_contributed": 2,
            "prs_opened": 1,
            "prs_merged": 1,
        }
        kwargs = mock_outcomes.call_args.kwargs
        assert kwargs["source_product"] == "replay_vision"
        assert kwargs["source_type"] == "scanner_finding"
        assert kwargs["extra_equals"] == {"scanner_id": str(scanner.id)}
