from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    CheckoutComResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.payments import (
    checkout_com_payments_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

PAGE_LIMIT_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.payments.SEARCH_PAGE_LIMIT"
)
LOOKUP_BUDGET_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.payments.MAX_FANOUT_LOOKUPS_PER_SYNC"
)
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports.make_tracked_session"
)

NOW = "2024-03-01T00:00:00Z"


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None) -> None:
        self.status_code = status_code
        self._json_data = json_data

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error for url")


class _FakeSession:
    """Replays queued search (POST) and lookup (GET) responses, recording each request."""

    def __init__(
        self,
        search_responses: Optional[list[_FakeResponse]] = None,
        lookup_responses: Optional[list[_FakeResponse]] = None,
    ) -> None:
        self._search_responses = list(search_responses or [])
        self._lookup_responses = list(lookup_responses or [])
        self.searches: list[dict[str, Any]] = []
        self.lookups: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.searches.append({"url": url, **kwargs})
        if not self._search_responses:
            raise AssertionError(f"unexpected search request to {url}")
        return self._search_responses.pop(0)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.lookups.append({"url": url, **kwargs})
        if not self._lookup_responses:
            raise AssertionError(f"unexpected lookup request to {url}")
        return self._lookup_responses.pop(0)


class _FakeManager(ResumableSourceManager[CheckoutComResumeConfig]):
    """In-memory stand-in for the Redis-backed manager (no `super().__init__`)."""

    def __init__(self, resume_state: Optional[CheckoutComResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[CheckoutComResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[CheckoutComResumeConfig]:
        return self._resume_state

    def save_state(self, data: CheckoutComResumeConfig) -> None:
        self.saved_states.append(data)


def _payment(
    payment_id: str,
    requested_on: str,
    customer_id: Optional[str] = None,
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    payment: dict[str, Any] = {
        "id": payment_id,
        "requested_on": requested_on,
        "amount": 1000,
        "currency": "USD",
        "approved": True,
        "status": "Captured",
        "_links": {"self": {"href": f"https://api.checkout.com/payments/{payment_id}"}},
    }
    if customer_id is not None:
        payment["customer"] = {"id": customer_id, "email": "customer@example.com"}
    if source_id is not None:
        payment["source"] = {"id": source_id, "type": "card"}
    return payment


def _search_page(payments: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(json_data={"total_count": len(payments), "data": payments})


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for chunk in source_response.items() for row in chunk]


def _source(
    schema_name: str,
    manager: Optional[_FakeManager] = None,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return checkout_com_payments_source(
        environment="production",
        client_id="ack_id",
        client_secret="secret",
        schema_name=schema_name,
        logger=mock.MagicMock(),
        resumable_source_manager=manager or _FakeManager(),
        start_date=start_date,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


@freeze_time(NOW)
class TestPaymentsWindowWalking:
    @mock.patch(PAGE_LIMIT_PATCH, 2)
    @mock.patch(SESSION_PATCH)
    def test_full_page_subdivides_window_and_yields_ascending(self, mock_make_session):
        # The full-range page comes back full (== limit), so the range splits in half;
        # each half fits in one page and is provably complete.
        session = _FakeSession(
            search_responses=[
                _search_page(
                    [
                        _payment("pay_2", "2024-02-29T18:00:00Z"),
                        _payment("pay_1", "2024-02-29T06:00:00Z"),
                    ]
                ),
                _search_page([_payment("pay_1", "2024-02-29T06:00:00Z")]),
                _search_page([_payment("pay_2", "2024-02-29T18:00:00Z")]),
            ]
        )
        mock_make_session.side_effect = [session]
        manager = _FakeManager()

        rows = _rows(_source("payments", manager=manager, start_date="2024-02-29"))

        assert [row["id"] for row in rows] == ["pay_1", "pay_2"]
        assert all("_links" not in row for row in rows)
        assert [(s["json"]["from"], s["json"]["to"]) for s in session.searches] == [
            ("2024-02-29T00:00:00Z", "2024-03-01T00:00:00Z"),
            ("2024-02-29T00:00:00Z", "2024-02-29T12:00:00Z"),
            ("2024-02-29T12:00:00Z", "2024-03-01T00:00:00Z"),
        ]
        assert all(s["json"]["limit"] == 2 and s["auth"] is not None for s in session.searches)
        # Each completed window checkpoints its end, ascending.
        assert [state.search_window_to for state in manager.saved_states] == [
            "2024-02-29T12:00:00Z",
            "2024-03-01T00:00:00Z",
        ]

    @pytest.mark.parametrize(
        "start_date, should_use_incremental_field, last_value, expected_from",
        [
            (None, False, None, "2023-03-02T00:00:00Z"),
            ("2024-01-01", False, None, "2024-01-01T00:00:00Z"),
            ("2024-01-01", True, "2024-02-01T00:00:00Z", "2024-02-01T00:00:00Z"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_range_start_resolution(
        self, mock_make_session, start_date, should_use_incremental_field, last_value, expected_from
    ):
        session = _FakeSession(search_responses=[_search_page([])])
        mock_make_session.side_effect = [session]

        rows = _rows(
            _source(
                "payments",
                start_date=start_date,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )
        )

        assert rows == []
        assert session.searches[0]["json"]["from"] == expected_from
        assert session.searches[0]["json"]["to"] == NOW

    @mock.patch(SESSION_PATCH)
    def test_resume_checkpoint_wins_over_watermark(self, mock_make_session):
        session = _FakeSession(search_responses=[_search_page([])])
        mock_make_session.side_effect = [session]
        manager = _FakeManager(CheckoutComResumeConfig(search_window_to="2024-02-15T00:00:00Z"))

        _rows(
            _source(
                "payments",
                manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-02-01T00:00:00Z",
            )
        )

        assert session.searches[0]["json"]["from"] == "2024-02-15T00:00:00Z"

    @mock.patch(PAGE_LIMIT_PATCH, 1)
    @mock.patch(SESSION_PATCH)
    def test_full_page_at_minimum_window_yields_with_error(self, mock_make_session):
        # One-second range that still fills a page: subdivision can't go further, so the
        # window yields what it has and the truncation is loud instead of silent.
        session = _FakeSession(search_responses=[_search_page([_payment("pay_1", "2024-02-29T23:59:59Z")])])
        mock_make_session.side_effect = [session]
        logger = mock.MagicMock()

        response = checkout_com_payments_source(
            environment="production",
            client_id="ack_id",
            client_secret="secret",
            schema_name="payments",
            logger=logger,
            resumable_source_manager=_FakeManager(),
            start_date="2024-02-29T23:59:59Z",
        )
        rows = _rows(response)

        assert [row["id"] for row in rows] == ["pay_1"]
        assert len(session.searches) == 1
        logger.error.assert_called_once()


@freeze_time(NOW)
class TestPaymentActionsFanout:
    @pytest.mark.parametrize(
        "actions_payload",
        [
            {"items": [{"id": "act_1", "type": "Capture", "response_code": "10000"}]},
            [{"id": "act_1", "type": "Capture", "response_code": "10000"}],
            {"data": [{"id": "act_1", "type": "Capture", "response_code": "10000"}]},
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_fetches_actions_per_payment_and_tolerates_wrapper_shapes(self, mock_make_session, actions_payload):
        session = _FakeSession(
            search_responses=[_search_page([_payment("pay_1", "2024-02-29T06:00:00Z")])],
            lookup_responses=[_FakeResponse(json_data=actions_payload)],
        )
        mock_make_session.side_effect = [session]

        rows = _rows(_source("payment_actions"))

        assert rows == [
            {
                "id": "act_1",
                "type": "Capture",
                "response_code": "10000",
                "payment_id": "pay_1",
                "payment_requested_on": "2024-02-29T06:00:00Z",
            }
        ]
        assert session.lookups == [
            {
                "url": "https://api.checkout.com/payments/pay_1/actions",
                "auth": mock.ANY,
                "timeout": mock.ANY,
            }
        ]

    @mock.patch(LOOKUP_BUDGET_PATCH, 1)
    @mock.patch(SESSION_PATCH)
    def test_lookup_budget_stops_cleanly_without_checkpointing(self, mock_make_session):
        session = _FakeSession(
            search_responses=[
                _search_page(
                    [
                        _payment("pay_1", "2024-02-29T06:00:00Z"),
                        _payment("pay_2", "2024-02-29T18:00:00Z"),
                    ]
                )
            ],
            lookup_responses=[_FakeResponse(json_data={"items": [{"id": "act_1"}]})],
        )
        mock_make_session.side_effect = [session]
        manager = _FakeManager()
        logger = mock.MagicMock()

        response = checkout_com_payments_source(
            environment="production",
            client_id="ack_id",
            client_secret="secret",
            schema_name="payment_actions",
            logger=logger,
            resumable_source_manager=manager,
        )
        rows = _rows(response)

        # Only the budgeted lookup ran, the interrupted window is not checkpointed (the
        # next run re-covers it), and the stop is loud.
        assert [row["id"] for row in rows] == ["act_1"]
        assert len(session.lookups) == 1
        assert manager.saved_states == []
        logger.warning.assert_called_once()


@freeze_time(NOW)
class TestReferencedRecordFanout:
    @pytest.mark.parametrize(
        "schema_name, record_id, url",
        [
            ("customers", "cus_1", "https://api.checkout.com/customers/cus_1"),
            ("instruments", "src_1", "https://api.checkout.com/instruments/src_1"),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_fetches_each_referenced_record_once(self, mock_make_session, schema_name, record_id, url):
        # Two payments reference the same record; a third has no fetchable reference
        # (a one-off token is not a vault instrument, a missing customer is skipped).
        payments = [
            _payment("pay_1", "2024-02-29T06:00:00Z", customer_id="cus_1", source_id="src_1"),
            _payment("pay_2", "2024-02-29T07:00:00Z", customer_id="cus_1", source_id="src_1"),
            _payment("pay_3", "2024-02-29T08:00:00Z", source_id="tok_1"),
        ]
        session = _FakeSession(
            search_responses=[_search_page(payments)],
            lookup_responses=[_FakeResponse(json_data={"id": record_id, "_links": {}})],
        )
        mock_make_session.side_effect = [session]

        rows = _rows(_source(schema_name))

        assert rows == [{"id": record_id, "payment_requested_on": "2024-02-29T06:00:00Z"}]
        assert [lookup["url"] for lookup in session.lookups] == [url]

    @mock.patch(SESSION_PATCH)
    def test_deleted_record_is_skipped_and_sync_continues(self, mock_make_session):
        payments = [
            _payment("pay_1", "2024-02-29T06:00:00Z", customer_id="cus_gone"),
            _payment("pay_2", "2024-02-29T07:00:00Z", customer_id="cus_2"),
        ]
        session = _FakeSession(
            search_responses=[_search_page(payments)],
            lookup_responses=[_FakeResponse(status_code=404), _FakeResponse(json_data={"id": "cus_2"})],
        )
        mock_make_session.side_effect = [session]
        manager = _FakeManager()

        rows = _rows(_source("customers", manager=manager))

        assert [row["id"] for row in rows] == ["cus_2"]
        # A deleted record doesn't fail the window; it still checkpoints.
        assert [state.search_window_to for state in manager.saved_states] == [NOW]


class TestCheckoutComPaymentsSourceResponse:
    @pytest.mark.parametrize(
        "schema_name, primary_keys, partition_keys",
        [
            ("payments", ["id"], ["requested_on"]),
            ("payment_actions", ["payment_id", "id"], ["payment_requested_on"]),
            ("customers", ["id"], None),
            ("instruments", ["id"], None),
        ],
    )
    def test_response_metadata(self, schema_name, primary_keys, partition_keys):
        response = _source(schema_name)

        assert response.name == schema_name
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        # Windows walk oldest-first, so ascending watermark commits are safe.
        assert response.sort_mode == "asc"

    def test_unknown_schema_raises(self):
        with pytest.raises(ValueError):
            _source("nope")
