from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import elasticemail
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail import (
    AUTH_ERROR_MARKER,
    ElasticEmailAuthError,
    ElasticEmailResumeConfig,
    ElasticEmailRetryableError,
    _build_params,
    _build_url,
    _clamp_future_value_to_now,
    _format_datetime,
    _is_auth_error_body,
    elasticemail_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Elastic Email expects YYYY-MM-DDThh:mm:ss with no timezone offset.
        result = _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+" not in result and "Z" not in result


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestBuildParams:
    def test_events_incremental_adds_from_filter(self) -> None:
        params = _build_params(
            ELASTICEMAIL_ENDPOINTS["events"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["from"] == "2026-03-04T02:58:14"
        assert params["orderBy"] == "DateAscending"
        assert params["limit"] == elasticemail.PAGE_SIZE

    def test_events_without_cursor_has_no_from(self) -> None:
        params = _build_params(
            ELASTICEMAIL_ENDPOINTS["events"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert "from" not in params

    def test_full_refresh_endpoint_never_adds_from(self) -> None:
        # Contacts has no server-side time filter, so a cursor value must not leak into the request.
        params = _build_params(
            ELASTICEMAIL_ENDPOINTS["contacts"],
            offset=40,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "from" not in params
        assert params["offset"] == 40

    def test_templates_carries_required_scope_type(self) -> None:
        params = _build_params(
            ELASTICEMAIL_ENDPOINTS["templates"],
            offset=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params["scopeType"] == ["Personal", "Global"]


class TestBuildUrl:
    def test_expands_list_params_into_repeated_query(self) -> None:
        url = _build_url("/templates", {"limit": 1, "scopeType": ["Personal", "Global"]})
        assert url == "https://api.elasticemail.com/v4/templates?limit=1&scopeType=Personal&scopeType=Global"


class TestIsAuthErrorBody:
    @parameterized.expand(
        [
            ("401", 401, "", True),
            ("403", 403, "", True),
            ("400_apikey_expired", 400, '{"Error":"APIKey Expired"}', True),
            ("400_incorrect_key", 400, '{"Error":"Incorrect API key."}', True),
            ("400_generic_bad_request", 400, '{"Error":"Invalid date range"}', False),
            ("404", 404, '{"Error":"Not found"}', False),
            ("200", 200, "[]", False),
        ]
    )
    def test_is_auth_error_body(self, _name: str, status: int, body: str, expected: bool) -> None:
        assert _is_auth_error_body(status, body) is expected


def _make_response(status_code: int, *, json_body: Any = None, text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if json_body is not None:
        import json

        response._content = json.dumps(json_body).encode()
    elif text is not None:
        response._content = text.encode()
    return response


class _FakeSession:
    def __init__(self, response: requests.Response) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict[str, str], timeout: int) -> requests.Response:
        self.requested_urls.append(url)
        return self._response


class TestFetchPage:
    # Call the undecorated body so tests exercise the status handling without tenacity's retry/backoff.
    _fetch = staticmethod(elasticemail._fetch_page.__wrapped__)  # type: ignore[attr-defined]
    _url = "https://api.elasticemail.com/v4/contacts"

    def test_returns_list_on_ok(self) -> None:
        session = _FakeSession(_make_response(200, json_body=[{"Email": "a@b.com"}]))
        assert self._fetch(session, self._url, {}, MagicMock()) == [{"Email": "a@b.com"}]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable(self, _name: str, status: int) -> None:
        session = _FakeSession(_make_response(status, text="boom"))
        with pytest.raises(ElasticEmailRetryableError):
            self._fetch(session, self._url, {}, MagicMock())

    @parameterized.expand([("expired_key", 400, '{"Error":"APIKey Expired"}'), ("unauthorized", 401, "")])
    def test_auth_failures_raise_auth_error(self, _name: str, status: int, body: str) -> None:
        session = _FakeSession(_make_response(status, text=body))
        with pytest.raises(ElasticEmailAuthError) as exc:
            self._fetch(session, self._url, {}, MagicMock())
        assert AUTH_ERROR_MARKER in str(exc.value)

    def test_non_list_payload_raises_retryable(self) -> None:
        session = _FakeSession(_make_response(200, json_body={"Error": "unexpected"}))
        with pytest.raises(ElasticEmailRetryableError):
            self._fetch(session, self._url, {}, MagicMock())

    def test_non_json_body_raises_retryable(self) -> None:
        # A 200 with an HTML/proxy body must not propagate a raw JSONDecodeError past the retry layer.
        session = _FakeSession(_make_response(200, text="<html>gateway timeout</html>"))
        with pytest.raises(ElasticEmailRetryableError):
            self._fetch(session, self._url, {}, MagicMock())


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, "[]", True),
            ("expired_key", 400, '{"Error":"APIKey Expired"}', False),
            ("unauthorized", 401, "", False),
            ("forbidden", 403, "", False),
            # A non-auth error (e.g. a transient 500) should not be reported as an invalid key.
            ("server_error", 500, "boom", True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, body: str, expected: bool) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                elasticemail,
                "make_tracked_session",
                lambda **_: _FakeSession(_make_response(status, text=body)),
            )
            assert validate_credentials("key") is expected

    def test_transport_exception_is_invalid(self, monkeypatch: Any) -> None:
        class _Boom:
            def get(self, *a: Any, **k: Any) -> Any:
                raise requests.ConnectionError("down")

        monkeypatch.setattr(elasticemail, "make_tracked_session", lambda **_: _Boom())
        assert validate_credentials("key") is False


class _FakeBatcher:
    """Yields after every page so the save-after-batch contract is testable without 2000+ rows."""

    def __init__(self, **_kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, item: dict) -> None:
        self._rows.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._rows) > 0

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


class _FakeManager:
    def __init__(self, state: ElasticEmailResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ElasticEmailResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ElasticEmailResumeConfig | None:
        return self._state

    def save_state(self, data: ElasticEmailResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    def _patch(self, monkeypatch: Any, pages: dict[int, list[dict]]) -> list[int]:
        requested_offsets: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> list[dict]:
            # Offset is the last query param built by _build_params/_build_url.
            offset = int(url.split("offset=")[1].split("&")[0])
            requested_offsets.append(offset)
            return pages[offset]

        monkeypatch.setattr(elasticemail, "_fetch_page", fake_fetch)
        monkeypatch.setattr(elasticemail, "Batcher", _FakeBatcher)
        monkeypatch.setattr(elasticemail, "PAGE_SIZE", 2)
        return requested_offsets

    def _collect(self, manager: _FakeManager) -> list[dict]:
        rows: list[dict] = []
        for table in get_rows(
            api_key="key",
            endpoint="contacts",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(table)
        return rows

    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        offsets = self._patch(
            monkeypatch,
            {
                0: [{"Email": "a"}, {"Email": "b"}],
                2: [{"Email": "c"}, {"Email": "d"}],
                4: [{"Email": "e"}],  # short page → terminate
            },
        )
        rows = self._collect(_FakeManager())
        assert [r["Email"] for r in rows] == ["a", "b", "c", "d", "e"]
        assert offsets == [0, 2, 4]

    def test_saves_offset_after_each_non_final_page(self, monkeypatch: Any) -> None:
        self._patch(
            monkeypatch,
            {0: [{"Email": "a"}, {"Email": "b"}], 2: [{"Email": "c"}, {"Email": "d"}], 4: [{"Email": "e"}]},
        )
        manager = _FakeManager()
        self._collect(manager)
        # State is saved after the two full pages (next offsets 2 and 4); the short final page saves nothing.
        assert [s.offset for s in manager.saved] == [2, 4]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        offsets = self._patch(monkeypatch, {2: [{"Email": "c"}, {"Email": "d"}], 4: [{"Email": "e"}]})
        rows = self._collect(_FakeManager(ElasticEmailResumeConfig(offset=2)))
        assert offsets[0] == 2
        assert [r["Email"] for r in rows] == ["c", "d", "e"]

    def test_empty_first_page_terminates(self, monkeypatch: Any) -> None:
        offsets = self._patch(monkeypatch, {0: []})
        rows = self._collect(_FakeManager())
        assert rows == []
        assert offsets == [0]


class TestElasticemailSource:
    @parameterized.expand(
        [
            ("contacts", ["Email"], "DateAdded"),
            ("lists", ["ListName"], "DateAdded"),
            ("segments", ["Name"], None),
            ("campaigns", ["Name"], None),
            ("templates", ["Name"], "DateAdded"),
            ("events", ["TransactionID", "MsgID", "EventType", "EventDate"], "EventDate"),
            ("suppressions", ["Email"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = elasticemail_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "week"
