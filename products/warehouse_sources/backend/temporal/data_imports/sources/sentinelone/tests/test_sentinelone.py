import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone import (
    sentinelone as sentinelone_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone import (
    SentinelOneHostNotAllowedError,
    SentinelOneResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    _normalize_row,
    normalize_console_url,
    sentinelone_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import SENTINELONE_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The run-time SSRF host check lives in the sentinelone module; keep it a no-op unless a test drives it.
HOST_CHECK_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone._is_host_safe"
)


def _mock_response(*, status_code: int = 200, json_data: Any = None, location: Optional[str] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_data).encode() if json_data is not None else b""
    if location is not None:
        resp.headers["Location"] = location
    return resp


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"nextCursor": next_cursor}}


class TestNormalizeConsoleUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("usea1-example.sentinelone.net", "usea1-example.sentinelone.net"),
            ("https://usea1-example.sentinelone.net", "usea1-example.sentinelone.net"),
            ("http://usea1-example.sentinelone.net/", "usea1-example.sentinelone.net"),
            ("  usea1-example.sentinelone.net  ", "usea1-example.sentinelone.net"),
            ("usea1-example.sentinelone.net/web/api/v2.1", "usea1-example.sentinelone.net"),
            ("https://usea1-example.sentinelone.net/web/api/v2.1/threats", "usea1-example.sentinelone.net"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_console_url(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_incremental_builds_gte_filter_and_matching_sort(self):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS["threats"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert params["updatedAt__gte"] == "2024-01-01T00:00:00.000Z"
        assert params["sortBy"] == "updatedAt"
        assert params["sortOrder"] == "asc"
        assert params["limit"] == 1000

    def test_incremental_honors_user_chosen_field_over_default(self):
        # threats defaults to updatedAt; a user who picked createdAt must get createdAt__gte.
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS["threats"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="createdAt",
        )
        assert params["createdAt__gte"] == "2024-01-01T00:00:00.000Z"
        assert "updatedAt__gte" not in params
        assert params["sortBy"] == "createdAt"

    def test_incremental_without_watermark_has_no_filter(self):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS["agents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updatedAt",
        )
        assert "updatedAt__gte" not in params
        assert params["sortBy"] == "updatedAt"

    def test_full_refresh_sorts_by_stable_field_without_filter(self):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS["threats"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert not any(key.endswith("__gte") for key in params)
        assert params["sortBy"] == "createdAt"
        assert params["sortOrder"] == "asc"

    @pytest.mark.parametrize("endpoint", ["groups", "sites"])
    def test_full_refresh_only_endpoints_send_no_sort_or_filter(self, endpoint):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert params == {"limit": SENTINELONE_ENDPOINTS[endpoint].page_size}


class TestNormalizeRow:
    def test_hoists_threat_info_timestamps(self):
        row = {"id": "t1", "threatInfo": {"createdAt": "2024-01-01T00:00:00Z", "updatedAt": "2024-01-02T00:00:00Z"}}
        normalized = _normalize_row(row, SENTINELONE_ENDPOINTS["threats"])
        assert normalized["createdAt"] == "2024-01-01T00:00:00Z"
        assert normalized["updatedAt"] == "2024-01-02T00:00:00Z"

    def test_does_not_overwrite_existing_top_level_fields(self):
        row = {"id": "t1", "createdAt": "top", "threatInfo": {"createdAt": "nested"}}
        assert _normalize_row(row, SENTINELONE_ENDPOINTS["threats"])["createdAt"] == "top"

    def test_no_hoist_for_endpoints_without_nested_timestamps(self):
        row = {"id": "a1", "createdAt": "2024-01-01T00:00:00Z"}
        assert _normalize_row(row, SENTINELONE_ENDPOINTS["agents"]) == row


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(sentinelone_module, "make_tracked_session", return_value=session)

    @staticmethod
    def _probe_response(*, status_code=200, json_data=None, text=""):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (302, 303, 307)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        response.json.return_value = json_data
        return response

    def test_success(self):
        with self._patch_session(self._probe_response(status_code=200)):
            assert validate_credentials("example.sentinelone.net", "tok") == (True, None)

    def test_invalid_token(self):
        with self._patch_session(self._probe_response(status_code=401)):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert msg == "Invalid SentinelOne API token"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._probe_response(status_code=403)):
            assert validate_credentials("example.sentinelone.net", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._probe_response(status_code=403)):
            valid, msg = validate_credentials("example.sentinelone.net", "tok", schema_name="threats")
            assert valid is False
            assert msg is not None

    def test_scoped_probe_hits_the_endpoint_path(self):
        with self._patch_session(self._probe_response(status_code=200)) as patched:
            validate_credentials("example.sentinelone.net", "tok", schema_name="threats")
            url = patched.return_value.get.call_args.args[0]
            assert url == "https://example.sentinelone.net/web/api/v2.1/threats"
            assert patched.return_value.get.call_args.kwargs["params"] == {"limit": 1}

    def test_create_probe_hits_system_info(self):
        with self._patch_session(self._probe_response(status_code=200)) as patched:
            validate_credentials("example.sentinelone.net", "tok")
            url = patched.return_value.get.call_args.args[0]
            assert url == "https://example.sentinelone.net/web/api/v2.1/system/info"

    @pytest.mark.parametrize("bad_url", ["", "not a url!", "https://"])
    def test_invalid_console_url_short_circuits(self, bad_url):
        valid, msg = validate_credentials(bad_url, "tok")
        assert valid is False
        assert msg == "Invalid SentinelOne console URL"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with self._patch_session(self._probe_response(status_code=302)) as patched:
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert msg == sentinelone_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(sentinelone_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._probe_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_error_body_is_surfaced(self):
        body = {"errors": [{"title": "Bad request", "detail": "invalid filter"}]}
        with self._patch_session(self._probe_response(status_code=400, json_data=body)):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert msg == "Bad request: invalid filter"


class TestSentinelOneSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_key, partition_key",
        [
            ("threats", "id", "createdAt"),
            ("agents", "id", "createdAt"),
            ("activities", "id", "createdAt"),
            ("groups", "id", "createdAt"),
            ("sites", "id", "createdAt"),
        ],
    )
    def test_response_shape(self, endpoint, primary_key, partition_key):
        response = sentinelone_source(
            console_url="example.sentinelone.net",
            api_token="tok",
            endpoint=endpoint,
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
            job_id="job",
        )
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"


def _make_manager(resume_state: SentinelOneResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so it must be copied when each
    request is prepared rather than inspected after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    responses: list[Response],
    *,
    endpoint: str = "threats",
    manager: mock.MagicMock | None = None,
) -> tuple[list[dict[str, Any]], mock.MagicMock, list[dict[str, Any]], mock.MagicMock]:
    manager = manager or _make_manager()
    with (
        mock.patch(CLIENT_SESSION_PATCH) as MockSession,
        mock.patch(HOST_CHECK_PATCH, return_value=(True, None)),
    ):
        session = MockSession.return_value
        params = _wire(session, responses)
        source = sentinelone_source(
            console_url="example.sentinelone.net",
            api_token="tok",
            endpoint=endpoint,
            resumable_source_manager=manager,
            team_id=1,
            job_id="job",
        )
        rows = _rows(source)
    return rows, session, params, manager


class TestPagination:
    def test_follows_cursor_across_pages(self):
        rows, session, params, _ = _run(
            [
                _mock_response(json_data=_page([{"id": "1"}, {"id": "2"}], next_cursor="cur")),
                _mock_response(json_data=_page([{"id": "3"}])),
            ]
        )
        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # The cursor is bound to the query it was minted against — non-cursor params carry over.
        assert params[1]["cursor"] == "cur"
        assert params[1]["limit"] == 1000

    def test_saves_state_after_yield_only_when_more_pages(self):
        _, _, _, manager = _run([_mock_response(json_data=_page([{"id": "1"}]))])
        manager.save_state.assert_not_called()

        _, _, _, manager2 = _run(
            [
                _mock_response(json_data=_page([{"id": "1"}], next_cursor="cur")),
                _mock_response(json_data=_page([{"id": "2"}])),
            ]
        )
        saved = manager2.save_state.call_args.args[0]
        assert isinstance(saved, SentinelOneResumeConfig)
        assert "cursor=cur" in saved.next_url

    def test_resumes_from_saved_state(self):
        manager = _make_manager(
            SentinelOneResumeConfig(
                next_url="https://example.sentinelone.net/web/api/v2.1/threats?limit=1000&cursor=resume"
            )
        )
        rows, _, params, _ = _run([_mock_response(json_data=_page([{"id": "9"}]))], manager=manager)
        assert params[0]["cursor"] == "resume"
        assert [r["id"] for r in rows] == ["9"]

    def test_ignores_resume_url_on_foreign_host(self):
        # A poisoned resume URL must fall back to a fresh start on the console host, not be followed.
        manager = _make_manager(SentinelOneResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))
        rows, _, params, _ = _run([_mock_response(json_data=_page([{"id": "1"}]))], manager=manager)
        assert "cursor" not in params[0]
        assert [r["id"] for r in rows] == ["1"]

    def test_empty_page_terminates_even_with_cursor(self):
        rows, session, _, manager = _run([_mock_response(json_data=_page([], next_cursor="cur"))])
        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    def test_sites_rows_come_from_nested_data_key(self):
        payload = {"data": {"sites": [{"id": "s1"}], "allSites": {}}, "pagination": {"nextCursor": None}}
        rows, _, _, _ = _run([_mock_response(json_data=payload)], endpoint="sites")
        assert [r["id"] for r in rows] == ["s1"]

    def test_threat_rows_are_normalized(self):
        payload = _page([{"id": "t1", "threatInfo": {"createdAt": "2024-01-01T00:00:00Z"}}])
        rows, _, _, _ = _run([_mock_response(json_data=payload)])
        assert rows[0]["createdAt"] == "2024-01-01T00:00:00Z"

    def test_redirect_response_is_rejected(self):
        # An unexpected 3xx (potentially to an internal address) must be rejected, not followed (SSRF).
        with pytest.raises(ValueError):
            _run([_mock_response(status_code=302, location="https://evil.example/")])


class TestRunTimeHostCheck:
    def test_unsafe_console_host_raises(self):
        # The console URL is re-validated at sync time; an internal address is refused before any request.
        with (
            mock.patch(CLIENT_SESSION_PATCH),
            mock.patch(HOST_CHECK_PATCH, return_value=(False, "internal address")),
        ):
            source = sentinelone_source(
                console_url="10.0.0.1",
                api_token="tok",
                endpoint="threats",
                resumable_source_manager=_make_manager(),
                team_id=1,
                job_id="job",
            )
            with pytest.raises(SentinelOneHostNotAllowedError):
                _rows(source)
