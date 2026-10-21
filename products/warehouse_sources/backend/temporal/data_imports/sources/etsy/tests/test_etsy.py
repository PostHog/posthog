import json
import time
import logging
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
import time_machine
from unittest.mock import patch

import structlog
from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy import (
    DAILY_QUOTA_EXHAUSTED_ERROR,
    ETSY_HISTORY_START,
    MAX_OFFSET,
    MIN_WINDOW_SECONDS,
    PAGE_SIZE,
    RATE_LIMITED_ERROR,
    EtsyAPIError,
    EtsyRateLimitError,
    EtsyResumeConfig,
    _window_start,
    etsy_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import (
    ETSY_ENDPOINTS,
    LISTING_STATES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.source import EtsySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.etsy import EtsySourceConfig

_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy.make_tracked_session"
_API_KEY = "etsy-keystring-abcdef123456"
_SHARED_SECRET = "etsy-shared-secret-abcdef123456"
_REFRESH_TOKEN = "etsy-refresh-token-abcdef123456"
_LOGGER = structlog.get_logger(__name__)


def _response(
    payload: Any,
    *,
    status: int = 200,
    url: str = "https://api.etsy.com/v3/application/shops/1",
    headers: Optional[dict[str, str]] = None,
) -> Response:
    response = Response()
    response.status_code = status
    response.url = url
    response.reason = "OK" if status < 400 else "Error"
    response._content = json.dumps(payload).encode()
    response.headers.update(headers or {})
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
        self.post_json_bodies: list[dict[str, Any]] = []
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

    def post(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,  # noqa: A002 — matches requests' keyword name
        timeout: Optional[float] = None,
    ) -> Response:
        # `data` and `json` are separate keywords so a test can tell form encoding from a JSON body.
        self.post_bodies.append(dict(data or json or {}))
        if json is not None:
            self.post_json_bodies.append(dict(json))
        if not self._post_responses:
            raise AssertionError("unexpected extra token request")
        return self._post_responses.pop(0)


def _windowed_session(responses: list[Response], *, opened_at: Optional[int] = ETSY_HISTORY_START) -> _FakeSession:
    """A full-history walk asks when the shop opened before it generates any window."""
    return _FakeSession([_response({"shop_id": 1, "created_timestamp": opened_at}), *responses])


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


def _scripted_page(rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"count": total, "results": rows})


def _scripted_token(access_token: str = "token-1") -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": access_token, "expires_in": 3600, "token_type": "Bearer"})


def _scripted_window(
    responses: list[ScriptedResponse], opened_at: Optional[int] = ETSY_HISTORY_START
) -> list[ScriptedResponse]:
    return [ScriptedResponse(json={"shop_id": 1, "created_timestamp": opened_at}), *responses]


def _driver(shop_id: Optional[str] = "1") -> SourceDriver:
    return SourceDriver(
        EtsySource(),
        EtsySourceConfig(api_key=_API_KEY, shared_secret=_SHARED_SECRET, refresh_token=_REFRESH_TOKEN, shop_id=shop_id),
    )


def _run(
    endpoint: str,
    responses: list[ScriptedResponse],
    *,
    shop_id: Optional[str] = "1",
    resume_state: EtsyResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    return _driver(shop_id).run(endpoint, [_scripted_token(), *responses], resume_state=resume_state, **inputs)


def _get_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.method == "GET"]


def _walk_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in _get_requests(result) if request.path != "/v3/application/shops/1"]


class TestEtsyTransport:
    def test_secrets_are_redacted_and_api_key_header_is_set(self) -> None:
        result = _run("shop_sections", [_scripted_page([], 0)])
        assert result.raised is None
        kwargs = result.session_options[0]
        # Etsy rejects a keystring-only x-api-key, so the secret has to ride the same header.
        assert kwargs["headers"]["x-api-key"] == f"{_API_KEY}:{_SHARED_SECRET}"
        assert set(kwargs["redact_values"]) == {_API_KEY, _SHARED_SECRET, _REFRESH_TOKEN}
        # A custom credential header survives a redirect, so the session must not follow one.
        assert kwargs["allow_redirects"] is False
        assert _get_requests(result)[0].headers["x-api-key"] == f"{_API_KEY}:{_SHARED_SECRET}"

    def test_persistent_401_is_raised_rather_than_looping(self) -> None:
        result = _driver().run(
            "shop_sections",
            route(
                {
                    "/oauth/token": [_scripted_token("token-1"), _scripted_token("token-2")],
                    "/shops/1/sections": [ScriptedResponse(status=401, json={}), ScriptedResponse(status=401, json={})],
                }
            ),
        )
        assert isinstance(result.raised, HTTPError)
        assert [request.headers["authorization"] for request in _get_requests(result)] == [
            "Bearer token-1",
            "Bearer token-2",
        ]

    def test_client_error_logs_the_response_body(self, caplog: pytest.LogCaptureFixture) -> None:
        # requests' raise_for_status() message carries only the status and URL, so the body is the
        # only place Etsy's actual rejection reason (e.g. an invalid parameter) survives to be triaged.
        with caplog.at_level(logging.ERROR):
            result = _run("shop_sections", [ScriptedResponse(status=400, json={"error": "invalid min_created"})])

        assert isinstance(result.raised, HTTPError)
        assert any("invalid min_created" in record.message for record in caplog.records)

    def test_shop_id_is_discovered_when_not_configured(self) -> None:
        result = _run(
            "shop_sections",
            [ScriptedResponse(json={"user_id": 7, "shop_id": 4242}), _scripted_page(_rows(1), 1)],
            shop_id=None,
        )

        assert result.raised is None
        assert [request.path for request in _get_requests(result)] == [
            "/v3/application/users/me",
            "/v3/application/shops/4242/sections",
        ]

    def test_account_without_a_shop_fails_with_an_actionable_error(self) -> None:
        result = _run("shop_sections", [ScriptedResponse(json={"user_id": 7, "shop_id": None})], shop_id=None)
        assert isinstance(result.raised, EtsyAPIError)
        assert "no shop" in str(result.raised)

    @parameterized.expand([("../users/me",), ("42/receipts",), ("abc",), ("0",), ("-1",)])
    def test_non_numeric_shop_id_is_rejected_before_any_request(self, shop_id: str) -> None:
        # A configured shop ID is concatenated into /shops/{shop_id}, so a traversal or non-numeric
        # value must be rejected rather than sent as an authenticated request to another resource.
        result = _run("shop_sections", [], shop_id=shop_id)
        assert isinstance(result.raised, EtsyAPIError)
        assert "positive number" in str(result.raised)
        assert _get_requests(result) == []

    def test_single_object_endpoint_yields_the_body_as_one_row(self) -> None:
        result = _run(
            "shop",
            [ScriptedResponse(json={"shop_id": 1, "shop_name": "Testy"})],
            resume_state=EtsyResumeConfig(offset=5),
        )

        assert result.raised is None
        assert result.rows == [{"shop_id": 1, "shop_name": "Testy"}]
        assert _get_requests(result)[0].query == {}
        assert result.final_state is None

    def test_offset_pagination_stops_at_the_offset_ceiling(self) -> None:
        # Etsy rejects an offset above 12,000, so a state with more rows than that must terminate
        # rather than request an offset the API refuses.
        pages = [_scripted_page(_rows(PAGE_SIZE, key="listing_id"), 20_000) for _ in range(MAX_OFFSET // PAGE_SIZE + 1)]
        result = _run("listings", pages + [_scripted_page([], 0) for _ in range(len(LISTING_STATES) - 1)])

        assert result.raised is None
        assert len(result.rows) == MAX_OFFSET + PAGE_SIZE
        assert max(int(value) for value in result.params("offset") if value is not None) == MAX_OFFSET

    @parameterized.expand(
        [
            # Etsy meters QPS first and then a sliding 24 hour quota, and only the day's counter
            # comes back on the refusal, so the header is what tells a burst from an empty quota.
            ({"x-remaining-today": "0"}, DAILY_QUOTA_EXHAUSTED_ERROR),
            ({"x-remaining-today": "417"}, RATE_LIMITED_ERROR),
            ({"x-remaining-today": "unparseable"}, RATE_LIMITED_ERROR),
            ({}, RATE_LIMITED_ERROR),
        ]
    )
    def test_rate_limited_response_names_the_limit_it_hit(self, headers: dict[str, str], expected: str) -> None:
        # The tracked session has already retried this while honoring retry-after, so a bare 429
        # reaching the job names neither whose limit was hit nor when it clears.
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST":
                return _scripted_token()
            return ScriptedResponse(status=429, json={"error": "Too Many Requests"}, headers=headers)

        result = _driver().run("shop_sections", answer)
        assert isinstance(result.raised, EtsyRateLimitError)
        assert expected in str(result.raised)

    @time_machine.travel("2020-01-15", tick=False)
    def test_full_history_walk_starts_when_the_shop_opened(self) -> None:
        # Windows before the shop existed can only come back empty, and Etsy charges the app's
        # daily quota for every one of them, which is what a sync runs out of before it finishes.
        opened_at = int(time.time()) - 30 * 24 * 60 * 60
        result = _run("receipts", _scripted_window([_scripted_page(_rows(1), 1)], opened_at=opened_at))

        assert result.raised is None
        assert _get_requests(result)[0].path == "/v3/application/shops/1"
        windows = [(request.param("min_created"), request.param("max_created")) for request in _walk_requests(result)]
        assert windows == [(str(opened_at), str(int(time.time())))]

    @parameterized.expand(
        [
            ("etsy reports none", None),
            ("older than etsy", 5),
            ("clock skewed into the future", 4_000_000_000),
        ]
    )
    @time_machine.travel("2005-01-15", tick=False)
    def test_unusable_shop_opening_date_still_walks_all_history(self, _name: str, opened_at: Optional[int]) -> None:
        result = _run("receipts", _scripted_window([_scripted_page([], 0)], opened_at=opened_at))
        assert result.raised is None
        assert _walk_requests(result)[0].param("min_created") == str(ETSY_HISTORY_START)

    @time_machine.travel("2005-01-15", tick=False)
    def test_oversized_window_is_halved_instead_of_hitting_the_offset_ceiling(self) -> None:
        # First probe reports more rows than the offset ceiling can reach, so the slice splits.
        result = _run(
            "receipts",
            _scripted_window(
                [
                    _scripted_page(_rows(PAGE_SIZE), MAX_OFFSET + PAGE_SIZE + 1),
                    _scripted_page(_rows(1), 1),
                    _scripted_page(_rows(1, start=1), 1),
                ]
            ),
        )

        assert result.raised is None
        windows = [(request.param("min_created"), request.param("max_created")) for request in _walk_requests(result)]
        outer_start, outer_end = windows[0]
        assert windows[1][0] == outer_start
        assert windows[1][1] is not None
        assert windows[2] == (str(int(windows[1][1]) + 1), outer_end)
        # The oversized probe page is discarded, so only the halves' rows land.
        assert len(result.rows) == 2

    @time_machine.travel("2005-01-01 00:30:00", tick=False)
    def test_window_that_cannot_be_split_further_stops_at_the_offset_ceiling(self) -> None:
        # A one-hour slice is the floor, so an over-full one reads what it can and moves on.
        pages = [_scripted_page(_rows(PAGE_SIZE), 50_000) for _ in range(MAX_OFFSET // PAGE_SIZE + 1)]
        result = _run("receipts", _scripted_window(pages))

        assert result.raised is None
        window = _walk_requests(result)[0]
        assert window.param("max_created") is not None
        assert window.param("min_created") is not None
        assert int(window.param("max_created") or 0) - int(window.param("min_created") or 0) < MIN_WINDOW_SECONDS
        assert len(result.rows) == MAX_OFFSET + PAGE_SIZE

    @time_machine.travel("2005-01-15", tick=False)
    def test_resume_finishes_the_saved_window_then_continues_after_it(self) -> None:
        saved_end = ETSY_HISTORY_START + 1000
        result = _run(
            "receipts",
            [_scripted_page(_rows(1), PAGE_SIZE + 1), _scripted_page([], 0)],
            resume_state=EtsyResumeConfig(offset=PAGE_SIZE, window_start=ETSY_HISTORY_START, window_end=saved_end),
        )

        assert result.raised is None
        first, second = _walk_requests(result)
        assert (first.param("min_created"), first.param("max_created"), first.param("offset")) == (
            str(ETSY_HISTORY_START),
            str(saved_end),
            str(PAGE_SIZE),
        )
        assert second.param("min_created") == str(saved_end + 1)

    @time_machine.travel("2005-01-15", tick=False)
    def test_offset_advances_by_parent_rows_not_expanded_children(self) -> None:
        # Offset addresses receipts, so a page of 100 receipts advances by 100 even when it
        # expands into far more transactions.
        parents = [
            {"receipt_id": i, "transactions": [{"transaction_id": i * 2}, {"transaction_id": i * 2 + 1}]}
            for i in range(PAGE_SIZE)
        ]
        result = _run("transactions", _scripted_window([_scripted_page(parents, 150), _scripted_page([], 150)]))

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE * 2
        assert _walk_requests(result)[1].param("offset") == str(PAGE_SIZE)

    @time_machine.travel("2005-01-15", tick=False)
    def test_payments_resolve_each_ledger_page_and_drop_payments_already_seen(self) -> None:
        # A sale and its later refund are separate ledger entries for one payment, and a full
        # refresh does not merge on the primary key, so a repeat would land as a duplicate row.
        # A resumed attempt would start with no record of the payments already written, so the
        # walk restarts instead and saves no cursor.
        stale = EtsyResumeConfig(offset=PAGE_SIZE, window_start=ETSY_HISTORY_START, window_end=ETSY_HISTORY_START + 1)
        result = _driver().run(
            "payments",
            route(
                {
                    "/oauth/token": [_scripted_token()],
                    "/shops/1": [ScriptedResponse(json={"shop_id": 1, "created_timestamp": ETSY_HISTORY_START})],
                    "/payment-account/ledger-entries": [
                        _scripted_page(_rows(PAGE_SIZE, key="entry_id"), PAGE_SIZE + 2),
                        _scripted_page(_rows(2, start=PAGE_SIZE, key="entry_id"), PAGE_SIZE + 2),
                    ],
                    "/ledger-entries/payments": [
                        _scripted_page(_rows(2, start=1, key="payment_id"), 2),
                        _scripted_page(_rows(2, start=2, key="payment_id"), 2),
                    ],
                }
            ),
            resume_state=stale,
        )

        assert result.raised is None
        assert [row["payment_id"] for row in result.rows] == [1, 2, 3]
        assert result.saved_states == []
        ledger = [request for request in _walk_requests(result) if request.path.endswith("/ledger-entries")]
        assert (ledger[0].param("min_created"), ledger[0].param("offset")) == (str(ETSY_HISTORY_START), "0")
        lookups = [request for request in _get_requests(result) if request.path.endswith("/payments")]
        assert [request.param("ledger_entry_ids") for request in lookups] == [
            ",".join(str(i) for i in range(PAGE_SIZE)),
            f"{PAGE_SIZE},{PAGE_SIZE + 1}",
        ]

    def test_listing_inventory_yields_a_row_per_product_and_splits_a_batch_etsy_rejects(self) -> None:
        # Etsy 404s the whole batch when one listing is gone, which would otherwise fail every sync
        # of a shop that deleted a listing mid-walk.
        listing = {
            "listing_id": 11,
            "inventory": {
                "products": [{"product_id": 1, "sku": "A"}, {"product_id": 2, "sku": "B"}],
                "price_on_property": [200],
            },
        }
        result = _driver().run(
            "listing_inventory",
            route(
                {
                    "/oauth/token": [_scripted_token()],
                    "/shops/1/listings": [
                        _scripted_page(_rows(2, start=10, key="listing_id"), 2),
                        *[_scripted_page([], 0) for _ in range(len(LISTING_STATES) - 1)],
                    ],
                    "/listings/batch/inventory": [
                        ScriptedResponse(status=404, json={"error": "Listing not found"}),
                        ScriptedResponse(status=404, json={"error": "Listing not found"}),
                        _scripted_page([listing], 1),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"product_id": 1, "sku": "A", "price_on_property": [200], "listing_id": 11},
            {"product_id": 2, "sku": "B", "price_on_property": [200], "listing_id": 11},
        ]
        assert [
            request.param("listing_ids")
            for request in _get_requests(result)
            if request.path.endswith("/listings/batch/inventory")
        ] == ["10,11", "10", "11"]

    def test_seller_taxonomy_flattens_the_tree_without_looking_up_a_shop(self) -> None:
        tree: list[dict[str, Any]] = [
            {
                "id": 1,
                "level": 0,
                "parent_id": None,
                "children": [{"id": 2, "level": 1, "parent_id": 1, "children": []}],
            },
            {"id": 3, "level": 0, "parent_id": None, "children": []},
        ]
        result = _driver(shop_id=None).run(
            "seller_taxonomy_nodes",
            route({"/oauth/token": [_scripted_token()], "/seller-taxonomy/nodes": [_scripted_page(tree, 2)]}),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 1, "level": 0, "parent_id": None},
            {"id": 2, "level": 1, "parent_id": 1},
            {"id": 3, "level": 0, "parent_id": None},
        ]

    @parameterized.expand(
        [
            ("updated_timestamp", "min_last_modified"),
            ("created_timestamp", "min_created"),
            # An unrecognised cursor must not silently window on the wrong column.
            ("not_a_field", "min_created"),
            (None, "min_created"),
        ]
    )
    @time_machine.travel("2006-01-15", tick=False)
    def test_incremental_field_selects_the_matching_etsy_filter(
        self, incremental_field: Optional[str], expected_param: str
    ) -> None:
        cursor = 1_136_073_600  # 2006-01-01
        result = _run(
            "receipts",
            [_scripted_page([], 0)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
            incremental_field=incremental_field,
        )

        assert result.raised is None
        assert _walk_requests(result)[0].param(expected_param) == str(cursor)

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
    def test_configured_shop_id_still_probes_the_token(self) -> None:
        # Skipping the probe here would let a bogus keystring or refresh token pass source creation.
        with scripted_network([_scripted_token(), ScriptedResponse(json={"user_id": 1, "shop_id": None})]) as network:
            assert validate_credentials(_API_KEY, _SHARED_SECRET, _REFRESH_TOKEN, "77") == (True, None)

        assert [request.path for request in network.requests_log if request.method == "GET"] == [
            "/v3/application/users/me"
        ]

    @parameterized.expand(
        [
            (400, "Check your API keystring"),
            (401, "Check your API keystring"),
            (403, "Check your API keystring"),
            (500, "Check your API keystring"),
            # A throttle says nothing about the credentials, so telling the user to check them sends
            # them off rotating keys that are fine.
            (429, "rate limiting your app"),
        ]
    )
    def test_failed_probe_reports_a_message_without_raising(self, status: int, expected_fragment: str) -> None:
        # Two of each so the 401 re-mint path has something to replay against.
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST":
                return _scripted_token()
            return ScriptedResponse(status=status, json={})

        with scripted_network(answer):
            ok, error = validate_credentials(_API_KEY, _SHARED_SECRET, _REFRESH_TOKEN, None)

        assert ok is False
        assert error is not None and expected_fragment in error

    def test_account_without_a_shop_surfaces_its_own_message(self) -> None:
        with scripted_network([_scripted_token(), ScriptedResponse(json={"user_id": 1, "shop_id": None})]):
            ok, error = validate_credentials(_API_KEY, _SHARED_SECRET, _REFRESH_TOKEN, None)

        assert ok is False
        assert error is not None and "no shop" in error

    def test_invalid_shop_id_fails_validation_without_probing(self) -> None:
        # A malformed shop ID is caught up front, so no request is issued to authenticate.
        with scripted_network([]) as network:
            ok, error = validate_credentials(_API_KEY, _SHARED_SECRET, _REFRESH_TOKEN, "../users/me")

        assert ok is False
        assert error is not None and "positive number" in error
        assert network.requests_log == []


class TestEtsySourceResponse:
    @parameterized.expand([(name,) for name in ETSY_ENDPOINTS])
    @time_machine.travel("2005-01-15", tick=False)
    def test_source_response_shape(self, endpoint: str) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST":
                return _scripted_token()
            if request.path == "/v3/application/shops/1":
                return ScriptedResponse(json={"shop_id": 1, "created_timestamp": int(time.time())})
            return _scripted_page([], 0)

        result = _driver().run(endpoint, answer)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ETSY_ENDPOINTS[endpoint].primary_keys
        # Etsy documents no ordering within a page, so the watermark must only be written once the
        # run completes — which is what "desc" buys us.
        assert response.sort_mode == "desc"

    @time_machine.travel("2005-01-15", tick=False)
    def test_items_is_lazy_and_streams_rows(self) -> None:
        session = _windowed_session([_page(_rows(3), 3)])
        response = etsy_source(
            api_key=_API_KEY,
            shared_secret=_SHARED_SECRET,
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
