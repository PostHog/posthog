import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n import (
    N8nResumeConfig,
    _build_url,
    n8n_source,
    normalize_host,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None, *, next_cursor: str | None = None, drop_data: bool = False
) -> Response:
    body: dict[str, Any] = {"nextCursor": next_cursor}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _json_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = "Forbidden" if status_code == 403 else "OK"
    resp.url = "https://n.example.com/api/v1/insights/summary"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: N8nResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response], urls: list[str] | None = None) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        if urls is not None:
            urls.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return n8n_source("https://n.example.com", "key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_fails_validation(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("https://myorg.app.n8n.cloud", "key") is False

    def test_invalid_url_fails_validation(self):
        # A host that can't be normalized never reaches the network — just reports "not validated".
        assert validate_credentials("ftp://nope", "key") is False


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_cursor_after_each_page(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}], next_cursor="CURSOR_A"),
                _response([{"id": "2"}], next_cursor="CURSOR_B"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("tags", manager))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # State saved once per page that has a following page (not for the last page).
        saved = [call.args[0].next_cursor for call in manager.save_state.call_args_list]
        assert saved == ["CURSOR_A", "CURSOR_B"]
        # The second request carries the cursor from the first page.
        assert params[1]["cursor"] == "CURSOR_A"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "9"}], next_cursor=None)])

        manager = _make_manager(N8nResumeConfig(next_cursor="SAVED"))
        _rows(_source("workflows", manager))

        assert params[0]["cursor"] == "SAVED"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("workflows", _make_manager()))


class TestFanOut:
    @parameterized.expand(
        [
            (
                "project_users",
                _response([{"id": "u1", "email": "a@example.com"}], next_cursor=None),
                "/projects/p1/users",
                {"limit": 250},
            ),
            (
                "folders",
                _json_response({"count": 1, "data": [{"id": "f1", "name": "Ops"}]}),
                "/projects/p1/folders",
                {"sortBy": "createdAt:asc", "skip": 0, "take": 250},
            ),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_children_carry_project_id(self, endpoint, child_response, child_path, child_params, MockSession):
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(session, [_response([{"id": "p1", "name": "Team"}], next_cursor=None), child_response], urls)

        rows = _rows(_source(endpoint, _make_manager()))

        assert [row["projectId"] for row in rows] == ["p1"]
        assert urls[1].endswith(child_path)
        assert params[1] == child_params

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_test_cases_bind_workflow_and_run_ids(self, MockSession):
        session = MockSession.return_value
        urls: list[str] = []
        _wire(
            session,
            [
                _response([{"id": "w1"}], next_cursor=None),
                _response([{"id": "r1", "status": "completed"}], next_cursor=None),
                _response([{"id": "c1", "status": "success"}], next_cursor=None),
            ],
            urls,
        )

        rows = _rows(_source("test_cases", _make_manager()))

        assert urls[2].endswith("/workflows/w1/test-runs/r1/test-cases")
        assert [(row["workflowId"], row["testRunId"], row["id"]) for row in rows] == [("w1", "r1", "c1")]


def _summary(total: int) -> dict[str, Any]:
    return {"total": {"value": total, "deviation": None, "unit": "count"}}


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_walks_one_day_per_request_up_to_today(self, _name, last_value, resume_date, requested_days, mock_session):
        responses = [_json_response(_summary(day)) for day in range(len(requested_days))]
        if requested_days[0] == "2026-10-09":
            responses[0] = _json_response({"message": "license"}, status_code=403)
        mock_session.return_value.get.side_effect = responses
        manager = _make_manager(N8nResumeConfig(next_date=resume_date) if resume_date else None)

        rows = _rows(
            n8n_source(
                "https://n.example.com",
                "key",
                "insights_summary",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                db_incremental_field_last_value=last_value,
            )
        )

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert [parse_qs(urlparse(url).query)["startDate"][0][:10] for url in urls] == requested_days
        synced_days = [day for day in requested_days if day != "2026-10-09"]
        assert [row["date"] for row in rows] == synced_days
        assert rows[-1]["endDate"] == "2026-10-13T00:00:00.000Z"
        # Every day but today stages the next day before its row is yielded.
        saved = [call.args[0].next_date for call in manager.save_state.call_args_list]
        assert saved == synced_days[1:]

    @time_machine.travel("2026-10-12T15:00:00Z", tick=False)
    @mock.patch(f"{_MODULE}.INSIGHTS_BACKFILL_DAYS", (3, 1))
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_refused_at_every_window_raises_forbidden(self, mock_session):
        mock_session.return_value.get.side_effect = [_json_response({}, status_code=403)] * 2

        with pytest.raises(HTTPError, match="403 Client Error: Forbidden for url"):
            _rows(_source("insights_summary", _make_manager()))
