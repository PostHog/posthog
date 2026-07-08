import gzip
import json
import base64
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.hog_invocation_results.sql import INSERT_HOG_INVOCATION_RESULT_SQL
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def create_hog_invocation_result(
    team_id: int,
    function_id: str,
    invocation_id: str,
    *,
    function_kind: str = "hog_flow",
    invocation_status: str = "success",
    version: int = 1,
    is_deleted: int = 0,
    distinct_id: str = "user-1",
    person_id: str = "person-1",
    error_kind: str = "",
    error_message: str = "",
    scheduled_at: Optional[datetime] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    duration_ms: Optional[int] = 12,
    attempts: int = 1,
    is_retry: int = 0,
    invocation_globals: str = "{}",
) -> None:
    # Default to "now" so rows land inside the endpoint's default -7d window.
    scheduled = scheduled_at or datetime.now(tz=UTC)
    params: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "invocation_id": invocation_id,
        "parent_run_id": "",
        "status": invocation_status,
        "attempts": attempts,
        "is_retry": is_retry,
        "scheduled_at": scheduled,
        "first_scheduled_at": scheduled,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "error_kind": error_kind,
        "error_message": error_message,
        "event_uuid": "",
        "distinct_id": distinct_id,
        "person_id": person_id,
        "invocation_globals": invocation_globals,
        "version": version,
        "is_deleted": is_deleted,
    }
    sync_execute(INSERT_HOG_INVOCATION_RESULT_SQL, params)


class TestHogFlowInvocationResults(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Test Flow")

    def _list(self, params=None):
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/", params)

    def _detail(self, invocation_id: str):
        return self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/{invocation_id}/"
        )

    def _seed(self, invocation_id: str, **kwargs):
        create_hog_invocation_result(
            team_id=self.team.pk, function_id=str(self.hog_flow.pk), invocation_id=invocation_id, **kwargs
        )

    def test_returns_empty_when_no_invocations(self):
        res = self._list()
        assert res.status_code == status.HTTP_200_OK
        assert res.json() == []

    def test_returns_invocation(self):
        self._seed(
            "inv-1",
            invocation_status="failed",
            error_kind="HogVMError",
            error_message="boom",
            distinct_id="user-7",
            person_id="person-7",
            finished_at=datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
        )
        results = self._list().json()
        assert len(results) == 1
        row = results[0]
        assert row["invocation_id"] == "inv-1"
        assert row["status"] == "failed"
        assert row["error_message"] == "boom"
        assert row["distinct_id"] == "user-7"
        assert row["person_id"] == "person-7"
        assert "invocation_globals" not in row

    def test_collapses_lifecycle_rows_to_latest_version(self):
        # A started row (v1) and a finished row (v2) for the same invocation collapse to the latest.
        self._seed("inv-1", invocation_status="started", version=1, finished_at=None)
        self._seed(
            "inv-1",
            invocation_status="failed",
            version=2,
            error_message="late failure",
            finished_at=datetime(2024, 1, 1, 12, 0, 9, tzinfo=UTC),
        )
        results = self._list().json()
        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert results[0]["error_message"] == "late failure"

    def test_excludes_deleted_invocations(self):
        self._seed("inv-1", invocation_status="success", version=1)
        self._seed("inv-1", invocation_status="success", version=2, is_deleted=1)
        assert self._list().json() == []

    @parameterized.expand(
        [
            ("failed", {"inv-fail"}),
            ("success,failed", {"inv-ok", "inv-fail"}),
        ]
    )
    def test_filters_by_status(self, status_filter: str, expected_ids: set):
        self._seed("inv-ok", invocation_status="success")
        self._seed("inv-fail", invocation_status="failed")
        results = self._list({"status": status_filter}).json()
        assert {r["invocation_id"] for r in results} == expected_ids

    def test_filters_by_distinct_id(self):
        self._seed("inv-1", distinct_id="user-a")
        self._seed("inv-2", distinct_id="user-b")
        results = self._list({"distinct_id": "user-a"}).json()
        assert {r["invocation_id"] for r in results} == {"inv-1"}

    @parameterized.expand(
        [
            ({"after": "-15d"}, {"inv-mid", "inv-late"}),
            ({"after": "-30d", "before": "-5d"}, {"inv-early", "inv-mid"}),
            ({"after": "-15d", "before": "-5d"}, {"inv-mid"}),
        ]
    )
    def test_filters_by_time_range(self, params: dict, expected_ids: set):
        # Relative to now, since the endpoint defaults `after` to -7d.
        now = datetime.now(tz=UTC)
        self._seed("inv-early", scheduled_at=now - timedelta(days=20))
        self._seed("inv-mid", scheduled_at=now - timedelta(days=10))
        self._seed("inv-late", scheduled_at=now - timedelta(days=2))
        results = self._list(params).json()
        assert {r["invocation_id"] for r in results} == expected_ids

    def test_default_window_excludes_rows_older_than_7d(self):
        # No `after` → default -7d window bounds the partition scan, so older runs drop out.
        now = datetime.now(tz=UTC)
        self._seed("recent", scheduled_at=now - timedelta(days=2))
        self._seed("old", scheduled_at=now - timedelta(days=30))
        results = self._list().json()
        assert {r["invocation_id"] for r in results} == {"recent"}

    def test_after_filter_respects_team_timezone(self):
        # PT is UTC-7 in June, so after='2026-06-08T00:00:00' (no offset) resolves to 07:00 UTC.
        # The row at 06:00 UTC must be excluded and the one at 08:00 UTC included — a naive
        # conversion that read the bound as 00:00 UTC would wrongly include both.
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        self._seed("before-bound", scheduled_at=datetime(2026, 6, 8, 6, 0, 0, tzinfo=UTC))
        self._seed("after-bound", scheduled_at=datetime(2026, 6, 8, 8, 0, 0, tzinfo=UTC))
        results = self._list({"after": "2026-06-08T00:00:00", "before": "2026-06-09T00:00:00"}).json()
        assert {r["invocation_id"] for r in results} == {"after-bound"}

    def test_isolated_from_other_flow_and_function_kind(self):
        self._seed("inv-mine", invocation_status="success")
        # Same team, but a hog_function invocation and a different flow id must not leak in.
        create_hog_invocation_result(
            team_id=self.team.pk,
            function_id=str(self.hog_flow.pk),
            invocation_id="inv-fn",
            function_kind="hog_function",
        )
        create_hog_invocation_result(team_id=self.team.pk, function_id="some-other-flow", invocation_id="inv-other")
        results = self._list().json()
        assert {r["invocation_id"] for r in results} == {"inv-mine"}

    def test_respects_limit(self):
        for i in range(5):
            self._seed(f"inv-{i}")
        results = self._list({"limit": 2}).json()
        assert len(results) == 2

    def test_detail_returns_invocation_globals(self):
        # Legacy rows predate compression and are stored as raw JSON.
        self._seed("inv-1", invocation_status="failed", invocation_globals='{"event": {"event": "$pageview"}}')
        res = self._detail("inv-1")
        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert body["invocation_id"] == "inv-1"
        assert body["status"] == "failed"
        assert body["invocation_globals"] == {"event": {"event": "$pageview"}}

    def test_detail_decodes_gzip_base64_invocation_globals(self):
        # Current rows are gzip-compressed then base64-encoded by the producer.
        payload = {"event": {"event": "$pageview"}, "person": {"id": "p1"}, "groups": {}}
        encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode("utf-8"))).decode("utf-8")
        self._seed("inv-1", invocation_globals=encoded)
        body = self._detail("inv-1").json()
        assert body["invocation_globals"] == payload

    def test_detail_invocation_globals_degrades_to_empty_on_garbage(self):
        self._seed("inv-1", invocation_globals="not-valid-base64-or-json")
        assert self._detail("inv-1").json()["invocation_globals"] == {}

    def test_detail_404_for_unknown_invocation(self):
        assert self._detail("nope").status_code == status.HTTP_404_NOT_FOUND

    def test_personal_api_key_requires_person_read_scope(self):
        # Invocation inspection exposes distinct_id / person_id and the triggering payload, so a
        # hog_flow:read-only token must not be able to enumerate who a workflow ran for — person:read
        # is also required.
        self._seed("inv-1")
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        headers = {"authorization": f"Bearer {key}"}
        list_res = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/", headers=headers
        )
        assert list_res.status_code == 403, list_res.json()
        assert "person:read" in list_res.json().get("detail", "")
        detail_res = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/inv-1/", headers=headers
        )
        assert detail_res.status_code == 403, detail_res.json()
        assert "person:read" in detail_res.json().get("detail", "")

    def test_personal_api_key_with_person_read_scope_allowed(self):
        self._seed("inv-1", invocation_globals='{"event": {"event": "$pageview"}}')
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow + person",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:read", "person:read"],
        )
        headers = {"authorization": f"Bearer {key}"}
        list_res = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/", headers=headers
        )
        assert list_res.status_code == 200, list_res.json()
        assert {r["invocation_id"] for r in list_res.json()} == {"inv-1"}
        detail_res = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocation_results/inv-1/", headers=headers
        )
        assert detail_res.status_code == 200, detail_res.json()
        assert detail_res.json()["invocation_id"] == "inv-1"
