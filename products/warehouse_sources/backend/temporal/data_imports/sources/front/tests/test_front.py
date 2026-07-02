import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Optional

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.front import front as front_module
from products.warehouse_sources.backend.temporal.data_imports.sources.front.front import (
    FrontResumeConfig,
    FrontRetryableError,
    _build_initial_params,
    _build_url,
    _parse_retry_after,
    _resolve_after_value,
    _retry_wait,
    _to_unix_seconds,
    front_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import FRONT_ENDPOINTS

logger = structlog.get_logger()


def _response(
    status_code: int = 200,
    json_body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    if headers:
        resp.headers.update(headers)
    resp._content = json.dumps(json_body or {}).encode()
    return resp


class _FakeSession:
    def __init__(self, responses: list[Response]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> Response:
        self.requested_urls.append(url)
        return self._responses.pop(0)


@contextmanager
def _patched_session(session: Any) -> Iterator[None]:
    with patch.object(front_module, "make_tracked_session", return_value=session):
        yield


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://api2.frontapp.com/tags", {}) == "https://api2.frontapp.com/tags"

    def test_encodes_params(self) -> None:
        url = _build_url("https://api2.frontapp.com/events", {"limit": 15, "sort_order": "asc"})
        assert url.startswith("https://api2.frontapp.com/events?")
        assert "limit=15" in url
        assert "sort_order=asc" in url

    def test_encodes_bracketed_query_filter(self) -> None:
        url = _build_url("https://api2.frontapp.com/events", {"q[after]": 1700000000})
        # urlencode percent-encodes brackets; Front decodes them server-side.
        assert "q%5Bafter%5D=1700000000" in url


class TestToUnixSeconds:
    def test_aware_datetime(self) -> None:
        dt = datetime(2023, 1, 1, tzinfo=UTC)
        assert _to_unix_seconds(dt) == dt.timestamp()

    def test_naive_datetime_assumed_utc(self) -> None:
        assert _to_unix_seconds(datetime(2023, 1, 1)) == datetime(2023, 1, 1, tzinfo=UTC).timestamp()

    @parameterized.expand([("int", 1700000000), ("float", 1700000000.123)])
    def test_numeric_passthrough(self, _name: str, value: Any) -> None:
        assert _to_unix_seconds(value) == value


class TestResolveAfterValue:
    def test_not_incremental_returns_none(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["events"], False, 1700000000) is None

    def test_last_value_used(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["events"], True, 1700000000) == 1700000000

    def test_lookback_used_when_no_last_value(self) -> None:
        result = _resolve_after_value(FRONT_ENDPOINTS["events"], True, None)
        # events has a 365-day lookback, so a float timestamp in the past is returned
        assert isinstance(result, float)
        assert result < datetime.now(UTC).timestamp()

    def test_no_lookback_no_last_value_returns_none(self) -> None:
        # A config without a lookback (and not incremental) yields no "after" value
        assert _resolve_after_value(FRONT_ENDPOINTS["contacts"], True, None) is None


class TestBuildInitialParams:
    def test_events_incremental_sets_q_after(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["events"], True, 1700000000)
        assert params["q[after]"] == 1700000000
        assert params["limit"] == 15
        assert params["sort_by"] == "created_at"
        assert params["sort_order"] == "asc"

    def test_events_non_incremental_omits_q_after(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["events"], False, None)
        assert "q[after]" not in params

    def test_tags_full_refresh_params(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["tags"], False, None)
        assert params == {"limit": 100, "sort_by": "id", "sort_order": "asc"}

    def test_teammates_sends_no_params(self) -> None:
        # teammates takes no documented query params
        assert _build_initial_params(FRONT_ENDPOINTS["teammates"], False, None) == {}


class TestParseRetryAfter:
    @parameterized.expand([("seconds", "5", 5.0), ("none", None, None), ("non_numeric", "abc", None)])
    def test_parse(self, _name: str, value: Optional[str], expected: Optional[float]) -> None:
        assert _parse_retry_after(value) == expected


class TestRetryWait:
    def test_honors_retry_after(self) -> None:
        state = SimpleNamespace(outcome=SimpleNamespace(exception=lambda: FrontRetryableError("x", retry_after=10)))
        assert _retry_wait(state) == 10.0  # type: ignore[arg-type]

    def test_caps_retry_after(self) -> None:
        state = SimpleNamespace(outcome=SimpleNamespace(exception=lambda: FrontRetryableError("x", retry_after=120)))
        assert _retry_wait(state) == 60.0  # type: ignore[arg-type]

    def test_falls_back_to_backoff(self) -> None:
        state = SimpleNamespace(
            attempt_number=1,
            outcome=SimpleNamespace(exception=lambda: FrontRetryableError("x")),
        )
        assert _retry_wait(state) >= 0  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unauthorized", 401, True, False),
            ("forbidden_with_scope", 403, True, False),
            ("forbidden_without_scope", 403, False, True),
            ("ok", 200, True, True),
            ("not_found_token_valid", 404, False, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, require_scope: bool, expected_ok: bool) -> None:
        with _patched_session(_FakeSession([_response(status_code=status)])):
            ok, _msg = validate_credentials("tok", "/teammates", require_scope=require_scope)
        assert ok is expected_ok

    def test_connection_error_fails(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with _patched_session(session):
            ok, msg = validate_credentials("tok", "/teammates", require_scope=False)
        assert ok is False
        assert msg is not None


class TestGetRows:
    def _manager(self, resume: Optional[FrontResumeConfig] = None) -> MagicMock:
        manager = MagicMock()
        manager.can_resume.return_value = resume is not None
        manager.load_state.return_value = resume
        return manager

    def test_paginates_and_saves_state(self) -> None:
        session = _FakeSession(
            [
                _response(
                    json_body={
                        "_results": [{"id": "evt_1"}],
                        "_pagination": {"next": "https://api2.frontapp.com/events?page_token=p2"},
                    }
                ),
                _response(json_body={"_results": [{"id": "evt_2"}], "_pagination": {"next": None}}),
            ]
        )
        manager = self._manager()

        with _patched_session(session):
            batches = list(get_rows("tok", "events", logger, manager))

        assert batches == [[{"id": "evt_1"}], [{"id": "evt_2"}]]
        manager.save_state.assert_called_once_with(
            FrontResumeConfig(next_url="https://api2.frontapp.com/events?page_token=p2")
        )
        assert session.requested_urls[1] == "https://api2.frontapp.com/events?page_token=p2"

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api2.frontapp.com/events?page_token=resume"
        session = _FakeSession([_response(json_body={"_results": [{"id": "evt_9"}], "_pagination": {"next": None}})])
        manager = self._manager(resume=FrontResumeConfig(next_url=resume_url))

        with _patched_session(session):
            batches = list(get_rows("tok", "events", logger, manager))

        assert batches == [[{"id": "evt_9"}]]
        assert session.requested_urls[0] == resume_url

    def test_empty_page_does_not_terminate(self) -> None:
        # An empty `_results` page with a next link must keep paginating (deleted resources can
        # leave a page short without it being the last page).
        session = _FakeSession(
            [
                _response(
                    json_body={
                        "_results": [],
                        "_pagination": {"next": "https://api2.frontapp.com/tags?page_token=p2"},
                    }
                ),
                _response(json_body={"_results": [{"id": "tag_1"}], "_pagination": {"next": None}}),
            ]
        )
        manager = self._manager()

        with _patched_session(session):
            batches = list(get_rows("tok", "tags", logger, manager))

        assert batches == [[{"id": "tag_1"}]]
        assert len(session.requested_urls) == 2

    def test_retries_on_429(self) -> None:
        session = _FakeSession(
            [
                _response(status_code=429, headers={"retry-after": "0"}),
                _response(json_body={"_results": [{"id": "tag_1"}], "_pagination": {"next": None}}),
            ]
        )
        manager = self._manager()

        with _patched_session(session):
            batches = list(get_rows("tok", "tags", logger, manager))

        assert batches == [[{"id": "tag_1"}]]
        assert len(session.requested_urls) == 2


class TestFrontSourceResponse:
    @parameterized.expand(
        [
            ("events", "emitted_at", "week", "asc"),
            ("conversations", "created_at", "month", "asc"),
            ("accounts", "created_at", "month", "asc"),
            ("tags", "created_at", "month", "asc"),
        ]
    )
    def test_partitioned_endpoints(
        self, endpoint: str, partition_key: str, partition_format: str, sort_mode: str
    ) -> None:
        response = front_source("tok", endpoint, logger, MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.partition_format == partition_format
        assert response.sort_mode == sort_mode

    @parameterized.expand([("contacts",), ("teammates",), ("inboxes",), ("channels",), ("teams",)])
    def test_non_partitioned_endpoints(self, endpoint: str) -> None:
        response = front_source("tok", endpoint, logger, MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
