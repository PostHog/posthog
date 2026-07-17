from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone import (
    sentinelone as sentinelone_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone import (
    SentinelOneResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _extract_rows,
    _format_incremental_value,
    _next_page_url,
    _normalize_row,
    get_rows,
    normalize_console_url,
    sentinelone_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import SENTINELONE_ENDPOINTS


def _response(
    *, status_code: int = 200, json_data: Any = None, headers: Optional[dict[str, str]] = None, text: str = ""
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = headers or {}
    return response


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None, total: int | None = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"nextCursor": next_cursor, "totalItems": total or len(rows)}}


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


class TestUrlBuilding:
    def test_initial_url(self):
        url = _build_initial_url("example.sentinelone.net", SENTINELONE_ENDPOINTS["threats"], {"limit": 1000})
        assert url == "https://example.sentinelone.net/web/api/v2.1/threats?limit=1000"

    def test_next_page_url_carries_params_and_swaps_cursor(self):
        # The cursor is only valid for the exact query it was minted against, so the
        # incremental filter and sort params must survive pagination unchanged.
        url = "https://example.sentinelone.net/web/api/v2.1/threats?limit=1000&sortBy=updatedAt&updatedAt__gte=2024-01-01T00%3A00%3A00.000Z"
        next_url = _next_page_url(url, "cur123")
        query = parse_qs(urlparse(next_url).query)
        assert query["cursor"] == ["cur123"]
        assert query["limit"] == ["1000"]
        assert query["sortBy"] == ["updatedAt"]
        assert query["updatedAt__gte"] == ["2024-01-01T00:00:00.000Z"]

    def test_next_page_url_replaces_previous_cursor(self):
        url = "https://example.sentinelone.net/web/api/v2.1/threats?limit=1000&cursor=old"
        query = parse_qs(urlparse(_next_page_url(url, "new")).query)
        assert query["cursor"] == ["new"]


class TestExtractRows:
    @pytest.mark.parametrize(
        "endpoint, payload, expected_ids",
        [
            ("threats", {"data": [{"id": "1"}, {"id": "2"}]}, ["1", "2"]),
            ("sites", {"data": {"sites": [{"id": "3"}], "allSites": {"totalLicenses": 5}}}, ["3"]),
            ("threats", {"data": None}, []),
            ("threats", {}, []),
            ("sites", {"data": []}, []),
            ("sites", {"data": {"allSites": {}}}, []),
        ],
    )
    def test_extract(self, endpoint, payload, expected_ids):
        rows = _extract_rows(payload, SENTINELONE_ENDPOINTS[endpoint])
        assert [r["id"] for r in rows] == expected_ids


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

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials("example.sentinelone.net", "tok") == (True, None)

    def test_invalid_token(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert msg == "Invalid SentinelOne API token"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials("example.sentinelone.net", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("example.sentinelone.net", "tok", schema_name="threats")
            assert valid is False
            assert msg is not None

    def test_scoped_probe_hits_the_endpoint_path(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("example.sentinelone.net", "tok", schema_name="threats")
            url = patched.return_value.get.call_args.args[0]
            assert url == "https://example.sentinelone.net/web/api/v2.1/threats"
            assert patched.return_value.get.call_args.kwargs["params"] == {"limit": 1}

    def test_create_probe_hits_system_info(self):
        with self._patch_session(_response(status_code=200)) as patched:
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
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
            assert valid is False
            assert msg == sentinelone_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(sentinelone_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_error_body_is_surfaced(self):
        body = {"errors": [{"title": "Bad request", "detail": "invalid filter"}]}
        with self._patch_session(_response(status_code=400, json_data=body)):
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
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"


class TestGetRows:
    def _run(self, manager, responses, endpoint="threats"):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(sentinelone_module, "make_tracked_session", return_value=session):
            rows: list[Any] = []
            for batch in get_rows(
                console_url="example.sentinelone.net",
                api_token="tok",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
            ):
                rows.extend(batch)
        return rows, session

    def test_follows_cursor_across_pages(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(json_data=_page([{"id": "1"}, {"id": "2"}], next_cursor="cur"))
        page2 = _response(json_data=_page([{"id": "3"}]))
        rows, session = self._run(manager, [page1, page2])

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        second_url = session.get.call_args_list[1].args[0]
        query = parse_qs(urlparse(second_url).query)
        assert query["cursor"] == ["cur"]
        # Non-cursor params must be carried over — the cursor is bound to them.
        assert query["limit"] == ["1000"]

    def test_saves_state_after_yield_only_when_more_pages(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        last_page = _response(json_data=_page([{"id": "1"}]))
        self._run(manager, [last_page])
        manager.save_state.assert_not_called()

        manager2 = mock.MagicMock()
        manager2.can_resume.return_value = False
        page1 = _response(json_data=_page([{"id": "1"}], next_cursor="cur"))
        page2 = _response(json_data=_page([{"id": "2"}]))
        self._run(manager2, [page1, page2])
        saved = manager2.save_state.call_args.args[0]
        assert isinstance(saved, SentinelOneResumeConfig)
        assert "cursor=cur" in saved.next_url

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = SentinelOneResumeConfig(
            next_url="https://example.sentinelone.net/web/api/v2.1/threats?limit=1000&cursor=resume"
        )
        rows, session = self._run(manager, [_response(json_data=_page([{"id": "9"}]))])

        first_url = session.get.call_args_list[0].args[0]
        assert "cursor=resume" in first_url
        assert [r["id"] for r in rows] == ["9"]

    def test_ignores_resume_url_on_foreign_host(self):
        # A poisoned resume URL must fall back to the initial console URL, not be followed.
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = SentinelOneResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")
        rows, session = self._run(manager, [_response(json_data=_page([{"id": "1"}]))])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith("https://example.sentinelone.net/web/api/v2.1/threats")
        assert [r["id"] for r in rows] == ["1"]

    def test_empty_page_terminates(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        rows, session = self._run(manager, [_response(json_data=_page([], next_cursor="cur"))])
        assert rows == []
        assert session.get.call_count == 1

    def test_sites_rows_come_from_nested_data_key(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        payload = {"data": {"sites": [{"id": "s1"}], "allSites": {}}, "pagination": {"nextCursor": None}}
        rows, _session = self._run(manager, [_response(json_data=payload)], endpoint="sites")
        assert [r["id"] for r in rows] == ["s1"]

    def test_threat_rows_are_normalized(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        payload = _page([{"id": "t1", "threatInfo": {"createdAt": "2024-01-01T00:00:00Z"}}])
        rows, _session = self._run(manager, [_response(json_data=payload)])
        assert rows[0]["createdAt"] == "2024-01-01T00:00:00Z"

    def test_redirect_response_raises(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(sentinelone_module.SentinelOneHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_response(json_data=_page([{"id": "1"}]))])
        assert session.get.call_args.kwargs["allow_redirects"] is False


class TestRetryAfter:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, header, expected):
        response = mock.MagicMock()
        response.headers = header
        assert sentinelone_module._parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        state = mock.MagicMock()
        state.outcome.exception.return_value = sentinelone_module.SentinelOneRetryableError(
            "rate limited", retry_after=7.0
        )
        assert sentinelone_module._retry_wait(state) == 7.0
