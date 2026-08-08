import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay import (
    EbayClient,
    EbayResumeConfig,
    build_windows,
    check_endpoint_permissions,
    coerce_datetime,
    ebay_source,
    format_datetime,
    get_rows,
    resolve_filter_field,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.settings import (
    DEFAULT_BACKFILL_DAYS,
    EBAY_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_OVERLAP_SECONDS,
    MAX_FILTER_WINDOW_DAYS,
)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
PROD_HOST = "https://api.ebay.com"


def _response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.url = PROD_HOST
    response.text = json.dumps(json_data if json_data is not None else {})
    response.json.return_value = json_data if json_data is not None else {}
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
    )
    return response


class _FakeManager(ResumableSourceManager[EbayResumeConfig]):
    """Stands in for the Redis-backed manager; subclasses it so the source's type holds."""

    def __init__(self, state: Optional[EbayResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[EbayResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[EbayResumeConfig]:
        return self.state

    def save_state(self, data: EbayResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


class _FakeSession:
    """Records every request and serves canned bodies keyed by path."""

    def __init__(self, pages: Optional[dict[str, list[MagicMock]]] = None) -> None:
        self.pages = pages or {}
        self.gets: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params") or {}
        self.gets.append({"url": url, "params": params, "headers": kwargs.get("headers") or {}})
        path = url[len(PROD_HOST) :]
        queue = self.pages.get(path)
        if not queue:
            return _response(200, {})
        # The last canned response repeats, so a retry (e.g. after a 401) sees the same
        # status rather than falling through to an unrelated empty body.
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _page(config_name: str, rows: list[dict[str, Any]], has_next: bool = False) -> MagicMock:
    body: dict[str, Any] = {EBAY_ENDPOINTS[config_name].data_key: rows}
    if has_next:
        body["next"] = "https://api.ebay.com/next"
    return _response(200, body)


def _run(
    session: _FakeSession,
    endpoint: str,
    manager: Optional[_FakeManager] = None,
    should_use_incremental_field: bool = False,
    last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> tuple[list[list[dict[str, Any]]], _FakeManager]:
    manager = manager or _FakeManager()
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=session,
        ),
        freeze_time(NOW),
    ):
        batches = list(
            get_rows(
                access_token="tok-1",
                marketplace_id="EBAY_US",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
                incremental_field=incremental_field,
            )
        )
    return batches, manager


class TestHelpers:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00.000Z"),
            ("naive_is_utc", datetime(2026, 1, 15, 10, 0, 0), "2026-01-15T10:00:00.000Z"),
            (
                "other_offset_converted",
                datetime(2026, 1, 15, 2, 0, 0, tzinfo=UTC).astimezone(),
                "2026-01-15T02:00:00.000Z",
            ),
            ("millis_truncated", datetime(2026, 1, 15, 10, 0, 0, 123456, tzinfo=UTC), "2026-01-15T10:00:00.123Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: datetime, expected: str) -> None:
        assert format_datetime(value) == expected

    @parameterized.expand(
        [
            ("datetime_aware", datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 15, tzinfo=UTC)),
            ("datetime_naive", datetime(2026, 1, 15), datetime(2026, 1, 15, tzinfo=UTC)),
            ("date", date(2026, 1, 15), datetime(2026, 1, 15, tzinfo=UTC)),
            ("iso_z", "2026-01-15T10:00:00.000Z", datetime(2026, 1, 15, 10, 0, tzinfo=UTC)),
            ("iso_offset", "2026-01-15T02:00:00-08:00", datetime(2026, 1, 15, 10, 0, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
            ("empty", "", None),
            ("none", None, None),
        ]
    )
    def test_coerce_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        result = coerce_datetime(value)
        if expected is None:
            assert result is None
        else:
            assert result is not None
            assert result.astimezone(UTC) == expected

    @parameterized.expand(
        [
            # The user's chosen cursor decides which eBay filter field is sent — the
            # Fulfillment API spells them lowercase, Finances camelCase.
            ("orders_last_modified", "orders", "lastModifiedDate", True, "lastmodifieddate"),
            ("orders_creation", "orders", "creationDate", True, "creationdate"),
            ("orders_unknown_field", "orders", "somethingElse", True, "lastmodifieddate"),
            ("orders_full_refresh", "orders", "lastModifiedDate", False, "lastmodifieddate"),
            ("transactions", "transactions", "transactionDate", True, "transactionDate"),
            ("payouts", "payouts", "payoutDate", True, "payoutDate"),
            ("inventory_has_no_filter", "inventory_items", None, False, None),
            ("offers_have_no_filter", "offers", None, False, None),
        ]
    )
    def test_resolve_filter_field(
        self, _name: str, endpoint: str, incremental_field: Optional[str], incremental: bool, expected: Optional[str]
    ) -> None:
        assert resolve_filter_field(EBAY_ENDPOINTS[endpoint], incremental_field, incremental) == expected


class TestBuildWindows:
    def test_endpoint_without_filter_has_a_single_unfiltered_pass(self) -> None:
        assert build_windows(EBAY_ENDPOINTS["inventory_items"], NOW) == [None]

    def test_backfill_is_chunked_to_the_api_cap_and_covers_the_whole_range(self) -> None:
        # A single request spanning the backfill would exceed eBay's 90-day filter cap and
        # be rejected, so the range must arrive as contiguous sub-windows.
        windows = build_windows(EBAY_ENDPOINTS["transactions"], NOW)
        assert windows[0] is not None and windows[-1] is not None
        assert windows[0][0] == NOW - timedelta(days=DEFAULT_BACKFILL_DAYS)
        assert windows[-1][1] == NOW
        for window in windows:
            assert window is not None
            assert window[1] - window[0] <= timedelta(days=MAX_FILTER_WINDOW_DAYS)
        for earlier, later in zip(windows, windows[1:]):
            assert earlier is not None and later is not None
            assert earlier[1] == later[0]

    def test_incremental_run_overlaps_the_stored_watermark(self) -> None:
        last_value = NOW - timedelta(days=2)
        windows = build_windows(EBAY_ENDPOINTS["orders"], NOW, True, last_value)
        assert windows == [(last_value - timedelta(seconds=INCREMENTAL_OVERLAP_SECONDS), NOW)]

    @parameterized.expand(
        [
            ("under_the_cap", timedelta(days=10), 1),
            ("just_over_the_cap", timedelta(days=MAX_FILTER_WINDOW_DAYS + 1), 2),
            ("several_windows", timedelta(days=200), 3),
        ]
    )
    def test_incremental_window_count(self, _name: str, age: timedelta, expected: int) -> None:
        windows = build_windows(EBAY_ENDPOINTS["transactions"], NOW, True, NOW - age)
        assert len(windows) == expected

    def test_future_watermark_is_clamped_to_now(self) -> None:
        # eBay rejects an inverted range, so a watermark ahead of now must not produce one.
        windows = build_windows(EBAY_ENDPOINTS["orders"], NOW, True, NOW + timedelta(days=5))
        assert len(windows) == 1
        assert windows[0] is not None
        assert windows[0][0] <= windows[0][1] == NOW

    def test_unparseable_watermark_falls_back_to_a_full_backfill(self) -> None:
        windows = build_windows(EBAY_ENDPOINTS["orders"], NOW, True, "not-a-date")
        assert windows[0] is not None
        assert windows[0][0] == NOW - timedelta(days=DEFAULT_BACKFILL_DAYS)


class TestEbayClient:
    def _client(
        self, session: _FakeSession, token_refresher: Optional[Callable[[str], str]] = None, token: str = "tok-1"
    ) -> EbayClient:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=session,
        ):
            return EbayClient(token, "EBAY_US", MagicMock(), token_refresher)

    def test_the_connections_token_is_sent_as_a_bearer(self) -> None:
        session = _FakeSession({"/sell/fulfillment/v1/order": [_page("orders", [])]})
        self._client(session).get("/sell/fulfillment/v1/order", {})
        assert session.gets[0]["headers"]["Authorization"] == "Bearer tok-1"

    def test_no_session_captures_http_samples(self) -> None:
        # Order/transaction/payout bodies carry buyer and seller PII, so no session the
        # client builds may write responses to the shared HTTP sample store.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=_FakeSession(),
        ) as make_session:
            EbayClient("tok-1", "EBAY_US", MagicMock())
        assert make_session.call_count >= 1
        for call in make_session.call_args_list:
            assert call.kwargs.get("capture") is False

    def test_expired_token_is_reminted_once_mid_sync(self) -> None:
        # User access tokens last two hours, which a large backfill outlives; a 401 must
        # refresh through the integration rather than fail the job.
        session = _FakeSession({"/sell/fulfillment/v1/order": [_response(401), _page("orders", [{"orderId": "1"}])]})
        refreshed: list[str] = []

        def refresher(current: str) -> str:
            refreshed.append(current)
            return "tok-2"

        client = self._client(session, refresher)
        assert client.get("/sell/fulfillment/v1/order", {}) == {"orders": [{"orderId": "1"}]}
        assert refreshed == ["tok-1"]
        assert session.gets[1]["headers"]["Authorization"] == "Bearer tok-2"

    def test_repeated_401_is_surfaced(self) -> None:
        session = _FakeSession({"/sell/fulfillment/v1/order": [_response(401), _response(401)]})
        client = self._client(session, lambda _current: "tok-2")
        with pytest.raises(requests.HTTPError):
            client.get("/sell/fulfillment/v1/order", {})

    def test_401_without_a_refresher_is_surfaced_immediately(self) -> None:
        # Validation probes have no refresher; a 401 there is a bad connection, not an expiry.
        session = _FakeSession({"/sell/fulfillment/v1/order": [_response(401), _page("orders", [])]})
        client = self._client(session)
        with pytest.raises(requests.HTTPError):
            client.get("/sell/fulfillment/v1/order", {})
        assert len(session.gets) == 1

    @parameterized.expand([("allowed", True, {}), ("not_allowed", False, None)])
    def test_404_handling(self, _name: str, allow_not_found: bool, expected: Optional[dict[str, Any]]) -> None:
        # getOffers answers 404 for a SKU with no offers — an empty result, not a failure.
        session = _FakeSession({"/sell/inventory/v1/offer": [_response(404)]})
        client = self._client(session)
        if expected is None:
            with pytest.raises(requests.HTTPError):
                client.get("/sell/inventory/v1/offer", {}, allow_not_found=allow_not_found)
        else:
            assert client.get("/sell/inventory/v1/offer", {}, allow_not_found=allow_not_found) == expected

    def test_marketplace_header_is_sent(self) -> None:
        session = _FakeSession({"/sell/fulfillment/v1/order": [_page("orders", [])]})
        client = self._client(session)
        client.get("/sell/fulfillment/v1/order", {})
        assert session.gets[0]["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"


class TestGetRows:
    def test_pagination_walks_pages_and_stops_when_next_is_absent(self) -> None:
        session = _FakeSession(
            {
                "/sell/fulfillment/v1/order": [
                    _page("orders", [{"orderId": "1"}], has_next=True),
                    _page("orders", [{"orderId": "2"}]),
                ]
            }
        )
        batches, manager = _run(
            session, "orders", should_use_incremental_field=True, last_value=NOW - timedelta(days=1)
        )

        assert [row["orderId"] for batch in batches for row in batch] == ["1", "2"]
        assert [call["params"]["offset"] for call in session.gets] == ["0", "1"]
        assert manager.cleared == 1

    def test_an_empty_page_ends_the_walk_even_when_next_is_present(self) -> None:
        # A `next` href with no rows must not loop forever.
        session = _FakeSession({"/sell/fulfillment/v1/order": [_page("orders", [], has_next=True)]})
        batches, _ = _run(session, "orders", should_use_incremental_field=True, last_value=NOW - timedelta(days=1))
        assert batches == []
        assert len(session.gets) == 1

    def test_state_is_saved_after_each_yielded_batch(self) -> None:
        session = _FakeSession(
            {
                "/sell/finances/v1/transaction": [
                    _page("transactions", [{"transactionId": "a"}], has_next=True),
                    _page("transactions", [{"transactionId": "b"}]),
                ]
            }
        )
        _, manager = _run(
            session,
            "transactions",
            should_use_incremental_field=True,
            last_value=NOW - timedelta(days=1),
            incremental_field="transactionDate",
        )
        assert [state.offset for state in manager.saved] == [1, 2]
        assert {state.window_start for state in manager.saved} == {
            format_datetime(NOW - timedelta(days=1, seconds=INCREMENTAL_OVERLAP_SECONDS))
        }

    def test_each_window_is_requested_with_its_own_filter(self) -> None:
        session = _FakeSession(
            {"/sell/finances/v1/transaction": [_page("transactions", [{"transactionId": str(i)}]) for i in range(4)]}
        )
        _run(
            session,
            "transactions",
            should_use_incremental_field=True,
            last_value=NOW - timedelta(days=200),
            incremental_field="transactionDate",
        )
        filters = [call["params"]["filter"] for call in session.gets]
        assert len(filters) == 3
        assert all(f.startswith("transactionDate:[") for f in filters)
        # Windows are contiguous: each one starts where the previous ended.
        ends = [f.split("..")[1].rstrip("]") for f in filters]
        starts = [f.split("[")[1].split("..")[0] for f in filters]
        assert starts[1:] == ends[:-1]
        assert ends[-1] == format_datetime(NOW)

    def test_resume_restarts_at_the_saved_window_and_offset(self) -> None:
        windows = build_windows(EBAY_ENDPOINTS["transactions"], NOW, True, NOW - timedelta(days=200))
        second = windows[1]
        assert second is not None
        session = _FakeSession(
            {"/sell/finances/v1/transaction": [_page("transactions", [{"transactionId": str(i)}]) for i in range(3)]}
        )
        manager = _FakeManager(EbayResumeConfig(window_start=format_datetime(second[0]), offset=400))
        _run(
            session,
            "transactions",
            manager=manager,
            should_use_incremental_field=True,
            last_value=NOW - timedelta(days=200),
            incremental_field="transactionDate",
        )
        # The already-completed first window is skipped, and the resumed one picks up at
        # the saved offset while later windows restart at 0.
        assert [call["params"]["offset"] for call in session.gets] == ["400", "0"]
        assert session.gets[0]["params"]["filter"].startswith(f"transactionDate:[{format_datetime(second[0])}")

    def test_resume_state_from_an_unrecognised_window_restarts_the_stream(self) -> None:
        # Windows shift when the watermark moves; a stale cursor must not silently skip data.
        session = _FakeSession({"/sell/fulfillment/v1/order": [_page("orders", [{"orderId": "1"}])]})
        manager = _FakeManager(EbayResumeConfig(window_start="1999-01-01T00:00:00.000Z", offset=900))
        _run(session, "orders", manager=manager, should_use_incremental_field=True, last_value=NOW - timedelta(days=1))
        assert session.gets[0]["params"]["offset"] == "0"

    def test_endpoint_without_a_filter_sends_none(self) -> None:
        session = _FakeSession({"/sell/inventory/v1/inventory_item": [_page("inventory_items", [{"sku": "A"}])]})
        _, manager = _run(session, "inventory_items")
        assert "filter" not in session.gets[0]["params"]
        assert session.gets[0]["params"]["limit"] == "100"
        assert manager.saved[0].window_start is None


class TestOffersFanOut:
    def _session(self) -> _FakeSession:
        return _FakeSession(
            {
                "/sell/inventory/v1/inventory_item": [
                    _page("inventory_items", [{"sku": "A"}, {"sku": "B"}, {}]),
                ],
                "/sell/inventory/v1/offer": [
                    _page("offers", [{"offerId": "o1", "sku": "A"}]),
                    _response(404),
                ],
            }
        )

    def test_offers_are_fetched_per_sku_and_missing_offers_are_skipped(self) -> None:
        session = self._session()
        batches, manager = _run(session, "offers")

        assert [row["offerId"] for batch in batches for row in batch] == ["o1"]
        offer_calls = [c for c in session.gets if c["url"].endswith("/offer")]
        # Only SKUs present on the parent row are queried; the row without one is skipped.
        assert [c["params"]["sku"] for c in offer_calls] == ["A", "B"]
        assert manager.saved == [EbayResumeConfig(parent_offset=3)]
        assert manager.cleared == 1

    def test_resume_skips_already_processed_parents(self) -> None:
        session = self._session()
        _run(session, "offers", manager=_FakeManager(EbayResumeConfig(parent_offset=50)))
        parent_call = next(c for c in session.gets if c["url"].endswith("/inventory_item"))
        assert parent_call["params"]["offset"] == "50"


class TestValidateCredentials:
    def _validate(self, session: _FakeSession, schema_name: Optional[str] = None) -> tuple[bool, bool]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=session,
        ):
            return validate_credentials("tok-1", "EBAY_US", schema_name)

    @parameterized.expand(
        [
            ("ok", 200, (True, False)),
            # A 403 is a genuine token missing a scope; the caller treats that differently.
            ("forbidden", 403, (False, True)),
            ("unauthorized", 401, (False, False)),
            ("server_error", 500, (False, False)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, bool]) -> None:
        page = _page("orders", []) if status == 200 else _response(status)
        assert self._validate(_FakeSession({"/sell/fulfillment/v1/order": [page]})) == expected

    def test_fanout_schema_probes_its_parent_listing(self) -> None:
        # getOffers needs a SKU we don't have at validation time, so the parent is probed.
        session = _FakeSession({"/sell/inventory/v1/inventory_item": [_page("inventory_items", [])]})
        assert self._validate(session, schema_name="offers") == (True, False)
        assert session.gets[0]["url"].endswith("/inventory_item")


class TestCheckEndpointPermissions:
    def _check(self, session: _FakeSession, endpoints: list[str]) -> dict[str, Optional[str]]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=session,
        ):
            return check_endpoint_permissions("tok-1", "EBAY_US", endpoints)

    def test_only_a_denial_is_reported_as_a_missing_scope(self) -> None:
        # A throttle or 5xx is transient — reporting it as a scope gap would push users to
        # deselect tables they can actually sync.
        session = _FakeSession(
            {
                "/sell/fulfillment/v1/order": [_page("orders", [])],
                "/sell/finances/v1/transaction": [_response(403)],
                "/sell/finances/v1/payout": [_response(429)],
            }
        )
        result = self._check(session, ["orders", "transactions", "payouts"])
        assert result["orders"] is None
        assert result["transactions"] is not None
        assert result["payouts"] is None

    def test_an_unusable_connection_leaves_every_endpoint_reachable(self) -> None:
        # A 401 is a connection problem that validate_credentials reports; flagging every table
        # as permission-denied here would be misleading.
        session = _FakeSession(dict.fromkeys((EBAY_ENDPOINTS[e].path for e in ENDPOINTS), [_response(401)]))
        assert self._check(session, list(ENDPOINTS)) == dict.fromkeys(ENDPOINTS)


class TestEbaySourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_matches_the_endpoint_settings(self, endpoint: str) -> None:
        config = EBAY_ENDPOINTS[endpoint]
        response = ebay_source(
            access_token="tok-1",
            marketplace_id="EBAY_US",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_items_is_lazy(self) -> None:
        # Building the response must not talk to eBay; the pipeline decides when to iterate.
        session = _FakeSession({"/sell/fulfillment/v1/order": [_page("orders", [{"orderId": "1"}])]})
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay.make_tracked_session",
            return_value=session,
        ):
            response = ebay_source(
                access_token="tok-1",
                marketplace_id="EBAY_US",
                endpoint="orders",
                logger=MagicMock(),
                resumable_source_manager=_FakeManager(),
            )
            assert session.gets == []
            items = iter(cast("Iterable[Any]", response.items()))
            assert next(items) == [{"orderId": "1"}]
            assert session.gets != []

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_incremental_endpoints_declare_a_matching_filter_field(self, endpoint: str) -> None:
        # An advertised incremental field with no filter mapping would silently do a full
        # scan every run while claiming to be incremental.
        config = EBAY_ENDPOINTS[endpoint]
        for field in config.incremental_fields:
            assert field["field"] in config.filter_fields
        assert bool(config.incremental_fields) == config.supports_time_filter
