import json
import time
from collections.abc import Iterable, Iterator
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest.mock import patch

import structlog
from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy import (
    ETSY_HISTORY_START,
    MAX_OFFSET,
    MIN_WINDOW_SECONDS,
    PAGE_SIZE,
    EtsyAPIError,
    EtsyResumeConfig,
    _window_start,
    etsy_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import (
    ETSY_ENDPOINTS,
    LISTING_STATES,
)

_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy.make_tracked_session"
_API_KEY = "etsy-keystring-abcdef123456"
_REFRESH_TOKEN = "etsy-refresh-token-abcdef123456"
_LOGGER = structlog.get_logger(__name__)


def _response(payload: Any, *, status: int = 200, url: str = "https://api.etsy.com/v3/application/shops/1") -> Response:
    response = Response()
    response.status_code = status
    response.url = url
    response.reason = "OK" if status < 400 else "Error"
    response._content = json.dumps(payload).encode()
    return response


def _page(rows: list[dict[str, Any]], total: int) -> Response:
    return _response({"count": total, "results": rows})


def _rows(count: int, start: int = 0, key: str = "receipt_id") -> list[dict[str, Any]]:
    return [{key: start + i} for i in range(count)]


def _token(access_token: str = "token-1") -> Response:
    return _response({"access_token": access_token, "expires_in": 3600, "token_type": "Bearer"})


class _FakeSession:
    """Stands in for the tracked session: replays canned responses and records every request."""

    def __init__(self, get_responses: list[Response], post_responses: Optional[list[Response]] = None) -> None:
        self.get_calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.post_bodies: list[dict[str, Any]] = []
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses) if post_responses is not None else [_token()]

    def get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Response:
        self.get_calls.append((url, dict(params or {}), dict(headers or {})))
        if not self._get_responses:
            raise AssertionError(f"unexpected extra GET: {url} {params}")
        return self._get_responses.pop(0)

    def post(self, url: str, json: Optional[dict[str, Any]] = None, timeout: Optional[float] = None) -> Response:  # noqa: A002 — matches requests' keyword name
        self.post_bodies.append(dict(json or {}))
        if not self._post_responses:
            raise AssertionError("unexpected extra token request")
        return self._post_responses.pop(0)


class _FakeManager(ResumableSourceManager[EtsyResumeConfig]):
    def __init__(self, resume: Optional[EtsyResumeConfig] = None) -> None:
        self._resume = resume
        self.saved: list[EtsyResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> Optional[EtsyResumeConfig]:
        return self._resume

    def save_state(self, data: EtsyResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


def _collect(
    session: _FakeSession,
    endpoint: str,
    *,
    shop_id: Optional[str] = "1",
    manager: Optional[_FakeManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> tuple[list[dict[str, Any]], _FakeManager]:
    active_manager = manager or _FakeManager()
    with patch(_SESSION_PATCH, return_value=session):
        batches: Iterator[list[dict[str, Any]]] = get_rows(
            api_key=_API_KEY,
            refresh_token=_REFRESH_TOKEN,
            shop_id=shop_id,
            endpoint=endpoint,
            logger=_LOGGER,
            resumable_source_manager=active_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )
        rows = [row for batch in batches for row in batch]
    return rows, active_manager


class TestEtsyTransport:
    def test_token_is_minted_from_the_refresh_token_and_reused(self) -> None:
        session = _FakeSession([_page(_rows(1), 1)])
        _collect(session, "shop_sections")

        assert session.post_bodies == [
            {"grant_type": "refresh_token", "client_id": _API_KEY, "refresh_token": _REFRESH_TOKEN}
        ]
        assert session.get_calls[0][2]["Authorization"] == "Bearer token-1"

    def test_secrets_are_redacted_and_api_key_header_is_set(self) -> None:
        session = _FakeSession([_page([], 0)])
        with patch(_SESSION_PATCH, return_value=session) as mock_session:
            list(
                get_rows(
                    api_key=_API_KEY,
                    refresh_token=_REFRESH_TOKEN,
                    shop_id="1",
                    endpoint="shop_sections",
                    logger=_LOGGER,
                    resumable_source_manager=_FakeManager(),
                )
            )

        kwargs = mock_session.call_args.kwargs
        assert kwargs["headers"]["x-api-key"] == _API_KEY
        assert set(kwargs["redact_values"]) == {_API_KEY, _REFRESH_TOKEN}
        # A custom credential header survives a redirect, so the session must not follow one.
        assert kwargs["allow_redirects"] is False

    def test_expired_access_token_is_reminted_once_and_the_request_replayed(self) -> None:
        session = _FakeSession(
            [_response({}, status=401), _page(_rows(2), 2)],
            post_responses=[_token("token-1"), _token("token-2")],
        )
        rows, _ = _collect(session, "shop_sections")

        assert len(rows) == 2
        assert len(session.post_bodies) == 2
        assert session.get_calls[1][2]["Authorization"] == "Bearer token-2"

    def test_persistent_401_is_raised_rather_than_looping(self) -> None:
        session = _FakeSession(
            [_response({}, status=401), _response({}, status=401)],
            post_responses=[_token("token-1"), _token("token-2")],
        )
        with pytest.raises(HTTPError):
            _collect(session, "shop_sections")

    def test_shop_id_is_discovered_when_not_configured(self) -> None:
        session = _FakeSession([_response({"user_id": 7, "shop_id": 4242}), _page(_rows(1), 1)])
        _collect(session, "shop_sections", shop_id=None)

        assert session.get_calls[0][0].endswith("/users/me")
        assert session.get_calls[1][0].endswith("/shops/4242/sections")

    def test_configured_shop_id_skips_discovery(self) -> None:
        session = _FakeSession([_page(_rows(1), 1)])
        _collect(session, "shop_sections", shop_id=" 99 ")

        assert session.get_calls[0][0].endswith("/shops/99/sections")

    def test_account_without_a_shop_fails_with_an_actionable_error(self) -> None:
        session = _FakeSession([_response({"user_id": 7, "shop_id": None})])
        with pytest.raises(EtsyAPIError, match="no shop"):
            _collect(session, "shop_sections", shop_id=None)

    @parameterized.expand([("../users/me",), ("42/receipts",), ("abc",), ("0",), ("-1",)])
    def test_non_numeric_shop_id_is_rejected_before_any_request(self, shop_id: str) -> None:
        # A configured shop ID is concatenated into /shops/{shop_id}, so a traversal or non-numeric
        # value must be rejected rather than sent as an authenticated request to another resource.
        session = _FakeSession([_page(_rows(1), 1)])
        with pytest.raises(EtsyAPIError, match="positive number"):
            _collect(session, "shop_sections", shop_id=shop_id)

        assert session.get_calls == []

    def test_single_object_endpoint_yields_the_body_as_one_row(self) -> None:
        session = _FakeSession([_response({"shop_id": 1, "shop_name": "Testy"})])
        rows, manager = _collect(session, "shop")

        assert rows == [{"shop_id": 1, "shop_name": "Testy"}]
        assert session.get_calls[0][1] == {}
        assert manager.cleared == 1

    def test_unpaginated_endpoint_sends_no_limit_or_offset(self) -> None:
        session = _FakeSession([_page([{"shop_section_id": 3}], 1)])
        rows, _ = _collect(session, "shop_sections")

        assert rows == [{"shop_section_id": 3}]
        assert session.get_calls[0][1] == {}

    def test_listings_fan_out_covers_every_state(self) -> None:
        session = _FakeSession([_page([{"listing_id": i}], 1) for i in range(len(LISTING_STATES))])
        rows, manager = _collect(session, "listings")

        assert [call[1]["state"] for call in session.get_calls] == list(LISTING_STATES)
        assert [call[1]["sort_on"] for call in session.get_calls] == ["created"] * len(LISTING_STATES)
        assert len(rows) == len(LISTING_STATES)
        assert manager.saved[0].listing_state == LISTING_STATES[0]

    def test_offset_pagination_walks_full_pages_then_stops_on_a_short_one(self) -> None:
        session = _FakeSession(
            [_page(_rows(PAGE_SIZE, key="listing_id"), 150), _page(_rows(50, start=100, key="listing_id"), 150)]
            + [_page([], 0) for _ in range(len(LISTING_STATES) - 1)]
        )
        rows, manager = _collect(session, "listings")

        assert len(rows) == 150
        assert [call[1]["offset"] for call in session.get_calls[:2]] == [0, PAGE_SIZE]
        assert [state.offset for state in manager.saved[:2]] == [PAGE_SIZE, 150]

    def test_offset_pagination_stops_at_the_offset_ceiling(self) -> None:
        # Etsy rejects an offset above 12,000, so a state with more rows than that must terminate
        # rather than request an offset the API refuses.
        pages = [_page(_rows(PAGE_SIZE, key="listing_id"), 20_000) for _ in range(MAX_OFFSET // PAGE_SIZE + 1)]
        session = _FakeSession(pages + [_page([], 0) for _ in range(len(LISTING_STATES) - 1)])
        rows, _ = _collect(session, "listings")

        assert len(rows) == MAX_OFFSET + PAGE_SIZE
        assert max(call[1]["offset"] for call in session.get_calls) == MAX_OFFSET

    @freeze_time("2005-01-15")
    def test_windowed_endpoint_sends_a_created_window_over_all_history(self) -> None:
        session = _FakeSession([_page(_rows(2), 2)])
        rows, _ = _collect(session, "receipts")

        params = session.get_calls[0][1]
        assert params["min_created"] == ETSY_HISTORY_START
        assert params["max_created"] == int(time.time())
        assert params["limit"] == PAGE_SIZE
        assert len(rows) == 2

    @freeze_time("2005-07-01")
    def test_windows_advance_until_the_range_is_covered(self) -> None:
        session = _FakeSession([_page([], 0) for _ in range(3)])
        _collect(session, "receipts")

        windows = [(call[1]["min_created"], call[1]["max_created"]) for call in session.get_calls]
        assert len(windows) == 3
        # Contiguous, non-overlapping, and finishing at "now".
        assert windows[0][0] == ETSY_HISTORY_START
        assert windows[1][0] == windows[0][1] + 1
        assert windows[2][0] == windows[1][1] + 1
        assert windows[-1][1] == int(time.time())

    @freeze_time("2005-01-15")
    def test_oversized_window_is_halved_instead_of_hitting_the_offset_ceiling(self) -> None:
        # First probe reports more rows than the offset ceiling can reach, so the slice splits.
        session = _FakeSession(
            [_page(_rows(PAGE_SIZE), MAX_OFFSET + 1), _page(_rows(1), 1), _page(_rows(1, start=1), 1)]
        )
        rows, _ = _collect(session, "receipts")

        windows = [(call[1]["min_created"], call[1]["max_created"]) for call in session.get_calls]
        outer_start, outer_end = windows[0]
        assert windows[1][0] == outer_start
        assert windows[2] == (windows[1][1] + 1, outer_end)
        # The oversized probe page is discarded, so only the halves' rows land.
        assert len(rows) == 2

    @freeze_time("2005-01-01 00:30:00")
    def test_window_that_cannot_be_split_further_stops_at_the_offset_ceiling(self) -> None:
        # A one-hour slice is the floor, so an over-full one reads what it can and moves on.
        pages = [_page(_rows(PAGE_SIZE), 50_000) for _ in range(MAX_OFFSET // PAGE_SIZE + 1)]
        session = _FakeSession(pages)
        rows, _ = _collect(session, "receipts")

        window = session.get_calls[0][1]
        assert window["max_created"] - window["min_created"] < MIN_WINDOW_SECONDS
        assert len(rows) == MAX_OFFSET + PAGE_SIZE

    @freeze_time("2005-01-15")
    def test_resume_finishes_the_saved_window_then_continues_after_it(self) -> None:
        saved_end = ETSY_HISTORY_START + 1000
        manager = _FakeManager(
            EtsyResumeConfig(offset=PAGE_SIZE, window_start=ETSY_HISTORY_START, window_end=saved_end)
        )
        session = _FakeSession([_page(_rows(1), PAGE_SIZE + 1), _page([], 0)])
        _collect(session, "receipts", manager=manager)

        first, second = session.get_calls[0][1], session.get_calls[1][1]
        assert (first["min_created"], first["max_created"], first["offset"]) == (
            ETSY_HISTORY_START,
            saved_end,
            PAGE_SIZE,
        )
        assert second["min_created"] == saved_end + 1

    @freeze_time("2005-01-15")
    def test_state_is_saved_after_each_batch_and_cleared_when_the_walk_finishes(self) -> None:
        session = _FakeSession([_page(_rows(PAGE_SIZE), 150), _page(_rows(50, start=100), 150)])
        _, manager = _collect(session, "receipts")

        assert [state.offset for state in manager.saved] == [PAGE_SIZE, 150]
        assert manager.saved[0].window_start == ETSY_HISTORY_START
        assert manager.cleared == 1

    @freeze_time("2005-01-15")
    def test_transactions_are_expanded_out_of_the_receipts_payload(self) -> None:
        session = _FakeSession(
            [
                _page(
                    [
                        {"receipt_id": 1, "transactions": [{"transaction_id": 10}, {"transaction_id": 11}]},
                        {"receipt_id": 2, "transactions": []},
                    ],
                    2,
                )
            ]
        )
        rows, _ = _collect(session, "transactions")

        assert rows == [{"transaction_id": 10}, {"transaction_id": 11}]
        assert session.get_calls[0][0].endswith("/shops/1/receipts")

    @freeze_time("2005-01-15")
    def test_offset_advances_by_parent_rows_not_expanded_children(self) -> None:
        # Offset addresses receipts, so a page of 100 receipts advances by 100 even when it
        # expands into far more transactions.
        parents = [
            {"receipt_id": i, "transactions": [{"transaction_id": i * 2}, {"transaction_id": i * 2 + 1}]}
            for i in range(PAGE_SIZE)
        ]
        session = _FakeSession([_page(parents, 150), _page([], 150)])
        rows, _ = _collect(session, "transactions")

        assert len(rows) == PAGE_SIZE * 2
        assert session.get_calls[1][1]["offset"] == PAGE_SIZE

    @parameterized.expand(
        [
            ("updated_timestamp", "min_last_modified"),
            ("created_timestamp", "min_created"),
            # An unrecognised cursor must not silently window on the wrong column.
            ("not_a_field", "min_created"),
            (None, "min_created"),
        ]
    )
    @freeze_time("2006-01-15")
    def test_incremental_field_selects_the_matching_etsy_filter(
        self, incremental_field: Optional[str], expected_param: str
    ) -> None:
        cursor = 1_136_073_600  # 2006-01-01
        session = _FakeSession([_page([], 0) for _ in range(2)])
        _collect(
            session,
            "receipts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
            incremental_field=incremental_field,
        )

        params = session.get_calls[0][1]
        assert expected_param in params
        assert params[expected_param] == cursor

    @freeze_time("2005-01-15")
    def test_full_refresh_ignores_a_stale_cursor(self) -> None:
        session = _FakeSession([_page([], 0)])
        _collect(session, "receipts", should_use_incremental_field=False, db_incremental_field_last_value=999_999_999)

        assert session.get_calls[0][1]["min_created"] == ETSY_HISTORY_START

    @parameterized.expand(
        [
            (False, None, ETSY_HISTORY_START),
            (True, None, ETSY_HISTORY_START),
            (True, 1_600_000_000, 1_600_000_000),
            # A cursor before Etsy existed (or a junk one) can only mean "start from the beginning".
            (True, 5, ETSY_HISTORY_START),
            (True, "not-a-number", ETSY_HISTORY_START),
        ]
    )
    def test_window_start_resolution(self, incremental: bool, cursor: Any, expected: int) -> None:
        assert _window_start(incremental, cursor) == expected


class TestEtsyValidateCredentials:
    def test_valid_credentials_resolve_the_shop(self) -> None:
        session = _FakeSession([_response({"user_id": 1, "shop_id": 5})])
        with patch(_SESSION_PATCH, return_value=session):
            assert validate_credentials(_API_KEY, _REFRESH_TOKEN, None) == (True, None)

    def test_configured_shop_id_still_probes_the_token(self) -> None:
        # Skipping the probe here would let a bogus keystring or refresh token pass source creation.
        session = _FakeSession([_response({"user_id": 1, "shop_id": None})])
        with patch(_SESSION_PATCH, return_value=session):
            assert validate_credentials(_API_KEY, _REFRESH_TOKEN, "77") == (True, None)

        assert session.get_calls[0][0].endswith("/users/me")

    @parameterized.expand([(400,), (401,), (403,), (500,)])
    def test_failed_probe_reports_a_message_without_raising(self, status: int) -> None:
        # Two of each so the 401 re-mint path has something to replay against.
        session = _FakeSession(
            [_response({}, status=status), _response({}, status=status)], post_responses=[_token(), _token()]
        )
        with patch(_SESSION_PATCH, return_value=session):
            ok, error = validate_credentials(_API_KEY, _REFRESH_TOKEN, None)

        assert ok is False
        assert error is not None

    def test_account_without_a_shop_surfaces_its_own_message(self) -> None:
        session = _FakeSession([_response({"user_id": 1, "shop_id": None})])
        with patch(_SESSION_PATCH, return_value=session):
            ok, error = validate_credentials(_API_KEY, _REFRESH_TOKEN, None)

        assert ok is False
        assert error is not None and "no shop" in error

    def test_transport_failure_does_not_raise(self) -> None:
        with patch(_SESSION_PATCH, side_effect=OSError("boom")):
            assert validate_credentials(_API_KEY, _REFRESH_TOKEN, None)[0] is False

    def test_invalid_shop_id_fails_validation_without_probing(self) -> None:
        # A malformed shop ID is caught up front, so no request is issued to authenticate.
        with patch(_SESSION_PATCH, side_effect=AssertionError("must not connect")):
            ok, error = validate_credentials(_API_KEY, _REFRESH_TOKEN, "../users/me")

        assert ok is False
        assert error is not None and "positive number" in error


class TestEtsySourceResponse:
    @parameterized.expand([(name,) for name in ETSY_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = etsy_source(
            api_key=_API_KEY,
            refresh_token=_REFRESH_TOKEN,
            shop_id="1",
            endpoint=endpoint,
            logger=_LOGGER,
            resumable_source_manager=_FakeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == ETSY_ENDPOINTS[endpoint].primary_keys
        # Etsy documents no ordering within a page, so the watermark must only be written once the
        # run completes — which is what "desc" buys us.
        assert response.sort_mode == "desc"

    @freeze_time("2005-01-15")
    def test_items_is_lazy_and_streams_rows(self) -> None:
        session = _FakeSession([_page(_rows(3), 3)])
        response = etsy_source(
            api_key=_API_KEY,
            refresh_token=_REFRESH_TOKEN,
            shop_id="1",
            endpoint="receipts",
            logger=_LOGGER,
            resumable_source_manager=_FakeManager(),
        )

        assert session.get_calls == []
        with patch(_SESSION_PATCH, return_value=session):
            batches = cast(Iterable[Any], response.items())
            rows = [row for batch in batches for row in batch]

        assert len(rows) == 3


class TestEtsyEndpointCatalog:
    @parameterized.expand([(name,) for name in ETSY_ENDPOINTS])
    def test_advertised_incremental_fields_map_to_a_real_filter(self, endpoint: str) -> None:
        config = ETSY_ENDPOINTS[endpoint]

        assert config.name == endpoint
        assert config.primary_keys
        for field in config.incremental_fields:
            # An advertised cursor with no Etsy filter behind it would sync a full refresh while
            # telling the user it was incremental.
            assert field["field"] in config.window_params
        if config.incremental_fields:
            assert config.default_window_param is not None
