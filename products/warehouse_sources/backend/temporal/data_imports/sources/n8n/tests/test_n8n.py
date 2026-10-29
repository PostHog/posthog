import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.n8n import N8nSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n import (
    N8nResumeConfig,
    _build_url,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.source import N8nSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n"


def _response(
    items: list[dict[str, str]] | None, *, next_cursor: str | None = None, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, object] = {"nextCursor": next_cursor}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(N8nSource(), N8nSourceConfig(host="https://n.example.com", api_key="key"))


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.app.n8n.cloud", "https://myorg.app.n8n.cloud"),
            ("myorg.app.n8n.cloud", "https://myorg.app.n8n.cloud"),
            ("https://n8n.example.com/", "https://n8n.example.com"),
            ("http://n8n.internal:5678", "http://n8n.internal:5678"),
            # A pasted API base URL is tolerated by trimming the /api/v1 suffix.
            ("https://myorg.app.n8n.cloud/api/v1", "https://myorg.app.n8n.cloud"),
            ("https://myorg.app.n8n.cloud/api/v1/", "https://myorg.app.n8n.cloud"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "ftp://example.com",
            "https://",
            # SSRF: urlparse reads the host as example.com but urllib3 connects to
            # 127.0.0.1 (backslash / userinfo confusion), so these must be rejected.
            r"http://127.0.0.1\@example.com",
            r"http://127.0.0.1%5c@example.com",
            "https://user@127.0.0.1",
        ],
    )
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    @pytest.mark.parametrize(
        "cloud, host, expect_raise",
        [
            # On cloud the API key would egress over the public internet, so plaintext
            # http is rejected while https is fine.
            (True, "http://n8n.example.com", True),
            (True, "https://n8n.example.com", False),
            # Self-hosted operators control their network path, so http stays allowed.
            (False, "http://n8n.internal:5678", False),
        ],
    )
    def test_http_requires_https_only_on_cloud(self, cloud, host, expect_raise):
        with mock.patch(f"{_MODULE}.is_cloud", return_value=cloud):
            if expect_raise:
                with pytest.raises(ValueError):
                    normalize_host(host)
            else:
                assert normalize_host(host) == host


class TestBuildUrl:
    def test_no_params_returns_base(self):
        assert _build_url("https://x/api/v1/workflows", {}) == "https://x/api/v1/workflows"


class TestValidateCredentials:
    def test_network_error_fails_validation(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("https://myorg.app.n8n.cloud", "key") is False

        assert {request.path for request in network.requests_log} == {"/api/v1/workflows"}

    def test_invalid_url_fails_validation(self):
        # A host that can't be normalized never reaches the network — just reports "not validated".
        assert validate_credentials("ftp://nope", "key") is False


class TestGetRows:
    def test_paginates_and_saves_cursor_after_each_page(self) -> None:
        result = _driver().run(
            "tags",
            [
                _response([{"id": "1"}], next_cursor="CURSOR_A"),
                _response([{"id": "2"}], next_cursor="CURSOR_B"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        # State saved once per page that has a following page (not for the last page).
        saved = [state.next_cursor for state in result.saved_states]
        assert saved == ["CURSOR_A", "CURSOR_B"]
        # The second request carries the cursor from the first page.
        assert result.params("cursor") == [None, "CURSOR_A", "CURSOR_B"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "workflows",
            [_response([{"id": "9"}], next_cursor=None)],
            resume_state=N8nResumeConfig(next_cursor="SAVED"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "9"}]
        assert result.params("cursor") == ["SAVED"]

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("workflows", [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestFanOut:
    @parameterized.expand(
        [
            (
                "project_users",
                ScriptedResponse(json={"nextCursor": None, "data": [{"id": "u1", "email": "a@example.com"}]}),
                "/projects/p1/users",
                {"limit": ("250",)},
            ),
            (
                "folders",
                ScriptedResponse(json={"count": 1, "data": [{"id": "f1", "name": "Ops"}]}),
                "/projects/p1/folders",
                {"sortBy": ("createdAt:asc",), "skip": ("0",), "take": ("250",)},
            ),
        ]
    )
    def test_project_children_carry_project_id(self, endpoint, child_response, child_path, child_params):
        result = _driver().run(endpoint, [_response([{"id": "p1", "name": "Team"}], next_cursor=None), child_response])

        assert result.raised is None
        assert [row["projectId"] for row in result.rows] == ["p1"]
        assert result.paths[1].endswith(child_path)
        assert result.queries[1] == child_params

    def test_test_cases_bind_workflow_and_run_ids(self):
        result = _driver().run(
            "test_cases",
            [
                _response([{"id": "w1"}], next_cursor=None),
                _response([{"id": "r1", "status": "completed"}], next_cursor=None),
                _response([{"id": "c1", "status": "success"}], next_cursor=None),
            ],
        )

        assert result.raised is None
        assert result.paths[2].endswith("/workflows/w1/test-runs/r1/test-cases")
        assert [(row["workflowId"], row["testRunId"], row["id"]) for row in result.rows] == [("w1", "r1", "c1")]


def _summary(total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"total": {"value": total, "deviation": None, "unit": "count"}})


class TestInsightsSummary:
    @parameterized.expand(
        [
            # The 3-day backfill exceeds the license, so the walk steps down to the 1-day one.
            ("backfill_steps_down_past_license_limit", None, None, ["2026-10-09", "2026-10-11", "2026-10-12"]),
            ("incremental_refetches_watermark_day", "2026-10-11T00:00:00Z", None, ["2026-10-11", "2026-10-12"]),
            ("resume_starts_at_saved_day", None, "2026-10-12", ["2026-10-12"]),
        ]
    )
    @time_machine.travel("2026-10-12T15:00:00Z", tick=False)
    @mock.patch(f"{_MODULE}.INSIGHTS_BACKFILL_DAYS", (3, 1))
    def test_walks_one_day_per_request_up_to_today(self, _name, last_value, resume_date, requested_days):
        responses = [_summary(day) for day in range(len(requested_days))]
        if requested_days[0] == "2026-10-09":
            responses[0] = ScriptedResponse(status=403, json={"message": "license"})
        inputs = {"incremental_field": "startDate", "db_incremental_field_last_value": last_value} if last_value else {}

        result = _driver().run(
            "insights_summary",
            responses,
            resume_state=N8nResumeConfig(next_date=resume_date) if resume_date else None,
            **inputs,
        )

        assert result.raised is None
        assert [str(value)[:10] for value in result.params("startDate")] == requested_days
        synced_days = [day for day in requested_days if day != "2026-10-09"]
        assert [row["date"] for row in result.rows] == synced_days
        assert result.rows[-1]["endDate"] == "2026-10-13T00:00:00.000Z"
        # Every day but today stages the next day before its row is yielded.
        assert [state.next_date for state in result.saved_states] == synced_days[1:]

    @time_machine.travel("2026-10-12T15:00:00Z", tick=False)
    @mock.patch(f"{_MODULE}.INSIGHTS_BACKFILL_DAYS", (3, 1))
    def test_refused_at_every_window_raises_forbidden(self):
        result = _driver().run("insights_summary", [ScriptedResponse(status=403, json={})] * 2)

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error: Forbidden for url" in str(result.raised)
