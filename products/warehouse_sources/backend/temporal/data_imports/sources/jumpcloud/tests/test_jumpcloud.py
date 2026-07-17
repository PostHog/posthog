import json
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud import jumpcloud
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.jumpcloud import (
    EVENTS_PAGE_SIZE,
    REST_PAGE_SIZE,
    JumpcloudResumeConfig,
    JumpcloudRetryableError,
    _parse_search_after,
    get_rows,
    jumpcloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import (
    ENDPOINTS,
    JUMPCLOUD_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: JumpcloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JumpcloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JumpcloudResumeConfig | None:
        return self._state

    def save_state(self, data: JumpcloudResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int, body: bytes = b"", headers: dict[str, str] | None = None):
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.headers.update(headers or {})
    return response


class TestRequest:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_exhaust_retries(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(jumpcloud._request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(JumpcloudRetryableError):
                jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert session.request.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_without_retrying(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert session.request.call_count == 1

    def test_429_carries_server_retry_after(self) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(429, headers={"Retry-After": "7"})
        with patch.object(jumpcloud._request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(JumpcloudRetryableError) as exc_info:
                jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert exc_info.value.retry_after == 7.0


class TestParseSearchAfter:
    @parameterized.expand(
        [
            ("valid_cursor", json.dumps([1747608000000, "abc"]), [1747608000000, "abc"]),
            ("missing_header", None, None),
            ("empty_string", "", None),
            ("garbage", "not-json", None),
            ("non_array", '{"a": 1}', None),
            ("empty_array", "[]", None),
        ]
    )
    def test_parsing(self, _name: str, raw: str | None, expected: list[Any] | None) -> None:
        assert _parse_search_after(raw, MagicMock()) == expected


class TestRestRows:
    @staticmethod
    def _collect(
        endpoint: str,
        pages: list[Any],
        manager: _FakeResumableManager,
        monkeypatch: Any,
        region: str = "us",
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            assert method == "GET"
            fetched_urls.append(url)
            skip = int(url.split("skip=")[1].split("&")[0])
            index = skip // REST_PAGE_SIZE
            page = pages[index] if index < len(pages) else []
            response = MagicMock()
            if JUMPCLOUD_ENDPOINTS[endpoint].api == "v1":
                response.json.return_value = {"totalCount": sum(len(p) for p in pages), "results": page}
            else:
                response.json.return_value = page
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            region=region,
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_v1_short_page_stops_without_saving_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect("users", [[{"_id": "a"}, {"_id": "b"}]], manager, monkeypatch)
        assert rows == [{"_id": "a"}, {"_id": "b"}]
        assert len(urls) == 1
        assert "sort=_id" in urls[0]
        assert manager.saved == []

    def test_v1_paginates_until_short_page_and_checkpoints_skip(self, monkeypatch: Any) -> None:
        full_page = [{"_id": str(i)} for i in range(REST_PAGE_SIZE)]
        manager = _FakeResumableManager()
        rows, urls = self._collect("users", [full_page, [{"_id": "last"}]], manager, monkeypatch)
        assert len(rows) == REST_PAGE_SIZE + 1
        assert len(urls) == 2
        # State is saved after the full page (pointing at the next offset), then we stop short.
        assert manager.saved == [JumpcloudResumeConfig(skip=REST_PAGE_SIZE)]

    def test_v1_resumes_from_saved_skip(self, monkeypatch: Any) -> None:
        full_page = [{"_id": str(i)} for i in range(REST_PAGE_SIZE)]
        manager = _FakeResumableManager(JumpcloudResumeConfig(skip=REST_PAGE_SIZE))
        rows, urls = self._collect("users", [full_page, [{"_id": "last"}]], manager, monkeypatch)
        # Resuming at skip=REST_PAGE_SIZE skips the already-synced first page.
        assert rows == [{"_id": "last"}]
        assert len(urls) == 1
        assert f"skip={REST_PAGE_SIZE}" in urls[0]

    def test_v2_bare_array_endpoint(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect("user_groups", [[{"id": "g1"}]], manager, monkeypatch)
        assert rows == [{"id": "g1"}]
        assert urls[0].startswith("https://console.jumpcloud.com/api/v2/usergroups?")

    def test_eu_region_targets_eu_console(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect("users", [[{"_id": "a"}]], manager, monkeypatch, region="eu")
        assert urls[0].startswith("https://console.eu.jumpcloud.com/")

    def test_v1_non_wrapped_payload_raises_value_error(self, monkeypatch: Any) -> None:
        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            response = MagicMock()
            response.json.return_value = [{"_id": "a"}]  # bare list where v1 wraps in "results"
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())
        with pytest.raises(ValueError):
            list(
                get_rows(
                    api_key="key",
                    endpoint="users",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )


class TestEventRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: list[tuple[list[dict], str | None]],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[dict]]:
        request_bodies: list[dict] = []
        call_index = 0

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            nonlocal call_index
            assert method == "POST"
            assert url.endswith("/insights/directory/v1/events")
            request_bodies.append(json_body)
            page, search_after_header = pages[call_index] if call_index < len(pages) else ([], None)
            call_index += 1
            response = MagicMock()
            response.json.return_value = page
            response.headers = {"X-Search_After": search_after_header} if search_after_header else {}
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint="events",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(page)
        return rows, request_bodies

    @freeze_time("2026-07-15T12:00:00Z")
    def test_first_sync_queries_the_90_day_retention_window(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, bodies = self._collect(manager, monkeypatch, [([{"id": "e1"}], None)])
        assert bodies == [
            {
                "service": ["all"],
                "start_time": "2026-04-16T12:00:00Z",
                "end_time": "2026-07-15T12:00:00Z",
                "limit": EVENTS_PAGE_SIZE,
            }
        ]

    @freeze_time("2026-07-15T12:00:00Z")
    def test_incremental_sync_starts_at_the_watermark(self, monkeypatch: Any) -> None:
        from datetime import UTC, datetime

        manager = _FakeResumableManager()
        _, bodies = self._collect(
            manager,
            monkeypatch,
            [([{"id": "e1"}], None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 10, 8, 30, tzinfo=UTC),
        )
        assert bodies[0]["start_time"] == "2026-07-10T08:30:00Z"
        assert bodies[0]["end_time"] == "2026-07-15T12:00:00Z"

    def test_follows_search_after_cursor_and_checkpoints_after_yield(self, monkeypatch: Any) -> None:
        full_page = [{"id": str(i)} for i in range(EVENTS_PAGE_SIZE)]
        cursor = [1747608000000, "evt"]
        manager = _FakeResumableManager()
        rows, bodies = self._collect(manager, monkeypatch, [(full_page, json.dumps(cursor)), ([{"id": "last"}], None)])
        assert len(rows) == EVENTS_PAGE_SIZE + 1
        # First request has no cursor; the second carries the header cursor back in the body.
        assert "search_after" not in bodies[0]
        assert bodies[1]["search_after"] == cursor
        # Both pages of one run query the identical pinned window (search_after requires it).
        assert bodies[1]["start_time"] == bodies[0]["start_time"]
        assert bodies[1]["end_time"] == bodies[0]["end_time"]
        assert manager.saved == [
            JumpcloudResumeConfig(
                search_after=cursor, start_time=bodies[0]["start_time"], end_time=bodies[0]["end_time"]
            )
        ]

    def test_full_page_without_search_after_header_terminates(self, monkeypatch: Any) -> None:
        # A full page whose response lacks the cursor header must stop rather than loop on page one.
        full_page = [{"id": str(i)} for i in range(EVENTS_PAGE_SIZE)]
        manager = _FakeResumableManager()
        rows, bodies = self._collect(manager, monkeypatch, [(full_page, None)])
        assert len(rows) == EVENTS_PAGE_SIZE
        assert len(bodies) == 1

    def test_resumes_with_saved_window_and_cursor(self, monkeypatch: Any) -> None:
        cursor = [123, "evt"]
        manager = _FakeResumableManager(
            JumpcloudResumeConfig(
                search_after=cursor, start_time="2026-07-01T00:00:00Z", end_time="2026-07-14T00:00:00Z"
            )
        )
        _, bodies = self._collect(manager, monkeypatch, [([{"id": "e2"}], None)])
        assert bodies[0]["search_after"] == cursor
        assert bodies[0]["start_time"] == "2026-07-01T00:00:00Z"
        assert bodies[0]["end_time"] == "2026-07-14T00:00:00Z"

    def test_non_list_payload_raises_value_error(self, monkeypatch: Any) -> None:
        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            response = MagicMock()
            response.json.return_value = {"error": "unexpected"}
            response.headers = {}
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())
        with pytest.raises(ValueError):
            list(
                get_rows(
                    api_key="key",
                    endpoint="events",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_key", 401, None, False),
            # A 403 at source-create means the key is real but this probe is out of the admin's
            # role — creation must go through.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "users", False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status, body=b"{}")
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, _error = validate_credentials("key", schema_name=schema_name)
        assert ok is expected_ok

    def test_events_schema_probes_the_insights_endpoint(self) -> None:
        session = MagicMock()
        session.post.return_value = _response_with_status(200)
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, _error = validate_credentials("key", schema_name="events")
        assert ok is True
        url = session.post.call_args.args[0]
        assert url == "https://api.jumpcloud.com/insights/directory/v1/events"
        assert session.post.call_args.kwargs["json"]["limit"] == 1

    def test_connection_error_returns_message(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None


class TestJumpcloudSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        response = jumpcloud_source(
            api_key="key",
            endpoint=name,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        config = JUMPCLOUD_ENDPOINTS[name]
        assert response.name == name
        assert response.primary_keys == [config.primary_key]
        # Directory Insights response ordering is undocumented, so the events stream defers
        # its watermark to job end (desc); everything else is plain ascending full refresh.
        assert response.sort_mode == ("desc" if config.api == "insights" else "asc")
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_partition_keys_are_stable_fields(self) -> None:
        # Guards against accidentally partitioning on a churning field like lastContact.
        assert all(cfg.partition_key in (None, "created", "timestamp") for cfg in JUMPCLOUD_ENDPOINTS.values())
