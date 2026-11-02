from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.luma import LumaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.luma import luma
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.luma import (
    LUMA_BASE_URL,
    LumaResumeConfig,
    LumaRetryableError,
    check_access,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.settings import (
    BLASTS_PATH,
    ENDPOINTS,
    EVENTS_PATH,
    GUESTS_PATH,
    LUMA_ENDPOINTS,
    TICKET_TYPES_PATH,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.source import LumaSource

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = luma._fetch_page.__wrapped__  # type: ignore[attr-defined]


def _driver() -> SourceDriver:
    return SourceDriver(LumaSource(), LumaSourceConfig(api_key="luma-key"))


def _page(entries: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"entries": entries, "has_more": next_cursor is not None, "next_cursor": next_cursor})


class TestGetRows:
    def test_follows_cursor_and_saves_state_after_yield(self) -> None:
        path = LUMA_ENDPOINTS["people"].path
        result = _driver().run("people", [_page([{"api_id": "per-1"}], "cur-2"), _page([{"api_id": "per-2"}])])
        assert result.raised is None
        assert result.paths == [path, path]
        assert result.params("pagination_cursor") == [None, "cur-2"]
        assert result.params("pagination_limit") == ["50", "50"]
        assert result.rows == [{"api_id": "per-1"}, {"api_id": "per-2"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert result.saved_states == [LumaResumeConfig(pagination_cursor="cur-2")]

    def test_resumes_from_saved_cursor(self) -> None:
        path = LUMA_ENDPOINTS["people"].path
        # The first page must never be fetched on resume.
        result = _driver().run(
            "people", [_page([{"api_id": "per-2"}])], resume_state=LumaResumeConfig(pagination_cursor="cur-2")
        )
        assert result.raised is None
        assert result.paths == [path]
        assert result.params("pagination_cursor") == ["cur-2"]
        assert result.rows == [{"api_id": "per-2"}]


class TestGuestsFanOut:
    @pytest.mark.parametrize(
        "endpoint,path,static_params",
        [
            ("event_blasts", BLASTS_PATH, {}),
            ("ticket_types", TICKET_TYPES_PATH, {"include_hidden": "true"}),
        ],
    )
    def test_unpaginated_children_are_fetched_per_event(
        self, endpoint: str, path: str, static_params: dict[str, str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(
                    [
                        {"api_id": "evt-1", "event": {"api_id": "evt-1"}},
                        {"api_id": "evt-2", "event": {"api_id": "evt-2"}},
                    ]
                ),
                _page([{"id": "row-a", "status": "sent"}]),
                _page([]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "row-a", "event_id": "evt-1", "status": "sent"}]
        assert result.paths == [EVENTS_PATH, path, path]
        assert result.params("event_id") == [None, "evt-1", "evt-2"]
        assert result.params("pagination_limit") == ["50", None, None]
        for name, value in static_params.items():
            assert result.params(name) == [None, value, value]

    def test_paginates_guests_within_an_event(self) -> None:
        result = _driver().run(
            "guests",
            [
                _page([{"api_id": "evt-1", "event": {"api_id": "evt-1"}}]),
                _page([{"api_id": "gst-a", "guest": {"api_id": "gst-a"}}], "gcur-2"),
                _page([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}]),
            ],
        )
        assert result.raised is None
        assert result.paths == [EVENTS_PATH, GUESTS_PATH, GUESTS_PATH]
        assert result.params("event_api_id") == [None, "evt-1", "evt-1"]
        assert result.params("pagination_cursor") == [None, None, "gcur-2"]
        assert [row["api_id"] for row in result.rows] == ["gst-a", "gst-b"]

    def test_saves_events_cursor_after_finishing_events_page(self) -> None:
        result = _driver().run(
            "guests",
            [
                _page([{"api_id": "evt-1", "event": {"api_id": "evt-1"}}], "ecur-2"),
                _page([{"api_id": "gst-a", "guest": {"api_id": "gst-a"}}]),
                _page([{"api_id": "evt-2", "event": {"api_id": "evt-2"}}]),
                _page([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}]),
            ],
        )
        assert result.raised is None
        assert result.paths == [EVENTS_PATH, GUESTS_PATH, EVENTS_PATH, GUESTS_PATH]
        assert result.params("pagination_cursor") == [None, None, "ecur-2", None]
        assert [row["event_api_id"] for row in result.rows] == ["evt-1", "evt-2"]
        # State points at the next *events* page, saved only after all its guests were yielded.
        assert result.saved_states == [LumaResumeConfig(pagination_cursor="ecur-2")]

    def test_resumes_from_saved_events_cursor(self) -> None:
        # The first events page must never be fetched on resume.
        result = _driver().run(
            "guests",
            [
                _page([{"api_id": "evt-2", "event": {"api_id": "evt-2"}}]),
                _page([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}]),
            ],
            resume_state=LumaResumeConfig(pagination_cursor="ecur-2"),
        )
        assert result.raised is None
        assert result.paths == [EVENTS_PATH, GUESTS_PATH]
        assert result.params("pagination_cursor") == ["ecur-2", None]
        assert result.rows == [{"api_id": "gst-b", "event_api_id": "evt-2"}]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"entries": [], "has_more": False}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(LumaRetryableError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    @parameterized.expand(
        [
            ("honors_retry_after", {"Retry-After": "45"}, 1, [45.0]),
            ("outlasts_one_minute_window", {}, 7, None),
        ]
    )
    def test_rate_limit_retries_wait_out_the_window(
        self, _name: str, headers: dict[str, str], rate_limited_calls: int, expected_waits: list[float] | None
    ) -> None:
        rate_limited = MagicMock(status_code=429, headers=headers)
        ok = self._session_returning(200).get.return_value
        session = MagicMock()
        session.get.side_effect = [rate_limited] * rate_limited_calls + [ok]
        waits: list[float] = []

        luma._fetch_page.retry_with(sleep=waits.append)(session, EVENTS_PATH, None, MagicMock())  # type: ignore[attr-defined]

        assert session.get.call_count == rate_limited_calls + 1
        if expected_waits is not None:
            assert waits == expected_waits
        else:
            assert sum(waits) > 60

    def test_exhausted_rate_limit_stays_retryable_with_sync_frequency_guidance(self) -> None:
        with pytest.raises(LumaRetryableError) as exc_info:
            _fetch_page_unwrapped(self._session_returning(429), EVENTS_PATH, None, MagicMock())
        observed_error = str(exc_info.value)
        source = LumaSource()
        assert not error_message_matches(observed_error, source.get_non_retryable_errors().keys())
        messages = [
            message
            for pattern, message in source.get_retry_exhausted_errors().items()
            if error_message_matches(observed_error, [pattern])
        ]
        assert messages and "sync less often" in messages[0]

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    @parameterized.expand(
        [
            ("has_more_false", {"entries": [{"api_id": "a"}], "has_more": False, "next_cursor": "cur-2"}),
            ("missing_next_cursor", {"entries": [{"api_id": "a"}], "has_more": True}),
            ("empty_next_cursor", {"entries": [{"api_id": "a"}], "has_more": True, "next_cursor": ""}),
        ]
    )
    def test_pagination_terminates(self, _name: str, body: dict) -> None:
        # `has_more` is authoritative — a lingering cursor on the final page must not loop forever.
        session = self._session_returning(200, body)
        _, next_cursor = _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())
        assert next_cursor is None

    @parameterized.expand([("bare_list", [{"api_id": "a"}]), ("missing_entries", {"has_more": False})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(LumaRetryableError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    def test_request_params_include_cursor_and_extras(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, GUESTS_PATH, "cur-9", MagicMock(), extra_params={"event_api_id": "evt-1"})
        args, kwargs = session.get.call_args
        assert args[0] == f"{LUMA_BASE_URL}{GUESTS_PATH}"
        assert kwargs["params"]["pagination_cursor"] == "cur-9"
        assert kwargs["params"]["event_api_id"] == "evt-1"
        assert kwargs["params"]["pagination_limit"] == luma.PAGE_SIZE

    def test_unpaginated_request_omits_pagination_limit(self) -> None:
        session = self._session_returning(200, {"entries": [{"id": "bst-a"}]})
        rows, next_cursor = _fetch_page_unwrapped(
            session, BLASTS_PATH, None, MagicMock(), extra_params={"event_id": "evt-1"}, paginate=False
        )
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"event_id": "evt-1"}
        assert rows == [{"id": "bst-a"}]
        assert next_cursor is None


class TestCheckAccess:
    @parameterized.expand(
        [
            ("missing_key", 400, False, 400, None),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, _ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access("luma-key") == (expected_status, expected_message)
        assert network.requests_log[0].path == EVENTS_PATH
        assert network.requests_log[0].param("pagination_limit") == "1"
        assert network.requests_log[0].headers["x-luma-api-key"] == "luma-key"

    @parameterized.expand(
        [
            ("missing_key", 400, False, "Invalid Luma API key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            assert validate_credentials("luma-key") == (expected_valid, expected_message)


class TestLumaSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_page([])))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == LUMA_ENDPOINTS[endpoint].primary_keys
        # `created_at` is nullable in Luma payloads, so we don't partition on it.
        assert response.partition_mode is None

    def test_guests_primary_key_includes_parent_event(self) -> None:
        # Guest rows aggregate across every event, so the key must be unique table-wide.
        assert LUMA_ENDPOINTS["guests"].primary_keys == ["event_api_id", "api_id"]
