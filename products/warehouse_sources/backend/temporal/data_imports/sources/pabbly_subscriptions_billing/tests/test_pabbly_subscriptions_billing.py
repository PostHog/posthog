from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing import (
    pabbly_subscriptions_billing as pabbly,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.pabbly_subscriptions_billing import (
    PAGE_SIZE,
    PabblyResumeConfig,
    PabblyRetryableError,
    check_access,
    get_rows,
    pabbly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.settings import (
    ENDPOINTS,
    PABBLY_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = pabbly._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PabblyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PabblyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PabblyResumeConfig | None:
        return self._state

    def save_state(self, data: PabblyResumeConfig) -> None:
        self.saved.append(data)


def _full_page(prefix: str) -> list[dict]:
    return [{"id": f"{prefix}{i}"} for i in range(PAGE_SIZE)]


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: dict[tuple[str, int], list[dict]],
    endpoint: str,
) -> list[dict]:
    def fake_fetch(
        session: Any, path: str, page: int, limit: int, logger: Any, ignore_no_data_errors: bool
    ) -> list[dict]:
        return pages.get((path, page), [])

    monkeypatch.setattr(pabbly, "_fetch_page", fake_fetch)
    monkeypatch.setattr(pabbly, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        api_key="pabbly-key",
        secret_key="pabbly-secret",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestGetRowsTopLevel:
    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, {("/customers", 1): [{"id": "1"}, {"id": "2"}]}, "customers")
        assert rows == [{"id": "1"}, {"id": "2"}]
        # The list ended on the first page, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_page_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/customers", 1): _full_page("a"),
            ("/customers", 2): [{"id": "last"}],
        }
        rows = _collect(manager, monkeypatch, pages, "customers")
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first full page (pointing at the next page), then we stop.
        assert [s.page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PabblyResumeConfig(page=3))
        # Pages 1 and 2 must never be re-fetched on resume.
        rows = _collect(manager, monkeypatch, {("/customers", 3): [{"id": "5"}]}, "customers")
        assert rows == [{"id": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, {}, "customers")
        assert rows == []
        assert manager.saved == []


class TestGetRowsFanOut:
    def test_fetches_children_for_each_parent_and_injects_parent_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/customers", 1): [{"id": "cus_1"}, {"id": "cus_2"}],
            ("/transactions/cus_1", 1): [{"id": "tra_1"}],
            # The API already stamps customer_id on this row; injection must not overwrite it.
            ("/transactions/cus_2", 1): [{"id": "tra_2", "customer_id": "already-set"}],
        }
        rows = _collect(manager, monkeypatch, pages, "transactions")
        assert rows == [
            {"id": "tra_1", "customer_id": "cus_1"},
            {"id": "tra_2", "customer_id": "already-set"},
        ]
        # A single short parent page means the whole sync fit in one pass — no state persisted.
        assert manager.saved == []

    def test_paginates_children_within_a_parent(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/products", 1): [{"id": "pro_1"}],
            ("/addons/pro_1", 1): _full_page("add_a"),
            ("/addons/pro_1", 2): [{"id": "add_last"}],
        }
        rows = _collect(manager, monkeypatch, pages, "addons")
        assert len(rows) == PAGE_SIZE + 1
        assert all(row["product_id"] == "pro_1" for row in rows)

    def test_saves_state_after_each_full_parent_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            ("/customers", 1): _full_page("cus_a"),
            ("/customers", 2): [{"id": "cus_last"}],
        }
        rows = _collect(manager, monkeypatch, pages, "refunds")
        assert rows == []
        # Resume state advances to parent page 2 only once every child of page 1 was yielded.
        assert [s.page for s in manager.saved] == [2]

    def test_resumes_from_saved_parent_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PabblyResumeConfig(page=2))
        pages = {
            # Parent page 1 must never be re-fetched on resume.
            ("/customers", 1): [{"id": "cus_wrong"}],
            ("/customers", 2): [{"id": "cus_1"}],
            ("/paymentmethods/cus_1", 1): [{"id": "pay_1"}],
        }
        rows = _collect(manager, monkeypatch, pages, "payment_methods")
        assert rows == [{"id": "pay_1", "customer_id": "cus_1"}]

    def test_parent_row_without_an_id_fails_fast(self, monkeypatch: Any) -> None:
        # A parent row missing its primary key must raise rather than silently drop its children.
        manager = _FakeResumableManager()
        pages = {
            ("/products", 1): [{"name": "no id"}],
        }
        with pytest.raises(KeyError):
            _collect(manager, monkeypatch, pages, "coupons")


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"status": "success", "data": []}
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
        with pytest.raises(PabblyRetryableError):
            _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False)

    def test_400_raises_when_endpoint_does_not_ignore_no_data_errors(self) -> None:
        session = self._session_returning(400)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False)

    def test_400_is_empty_page_when_endpoint_ignores_no_data_errors(self) -> None:
        session = self._session_returning(400)
        assert _fetch_page_unwrapped(session, "/addons/pro_1", 1, PAGE_SIZE, MagicMock(), True) == []

    def test_success_returns_data_rows(self) -> None:
        session = self._session_returning(200, {"status": "success", "data": [{"id": "1"}]})
        assert _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False) == [{"id": "1"}]

    def test_dict_data_is_wrapped_into_a_single_row(self) -> None:
        session = self._session_returning(200, {"status": "success", "data": {"id": "1"}})
        assert _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False) == [{"id": "1"}]

    def test_missing_data_key_is_empty_page(self) -> None:
        session = self._session_returning(200, {"status": "success"})
        assert _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False) == []

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "1"}])
        with pytest.raises(PabblyRetryableError):
            _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False)

    @parameterized.expand(
        [
            ("no_transaction_found", "No transaction found"),
            ("no_data_found", "No data found"),
        ]
    )
    def test_no_data_error_envelope_is_empty_page(self, _name: str, message: str) -> None:
        # Pabbly can answer "resource has no rows" as an HTTP 200 error envelope.
        session = self._session_returning(200, {"status": "error", "message": message})
        assert _fetch_page_unwrapped(session, "/refund/cus_1", 1, PAGE_SIZE, MagicMock(), True) == []

    def test_other_error_envelope_raises(self) -> None:
        session = self._session_returning(200, {"status": "error", "message": "Invalid user api"})
        with pytest.raises(ValueError, match="Invalid user api"):
            _fetch_page_unwrapped(session, "/customers", 1, PAGE_SIZE, MagicMock(), False)

    def test_sends_page_and_limit_params(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/subscriptions", 4, PAGE_SIZE, MagicMock(), False)
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 4, "limit": PAGE_SIZE}


class TestMakeSession:
    @patch(f"{pabbly.__name__}.make_tracked_session")
    def test_authenticates_with_http_basic(self, mock_session: MagicMock) -> None:
        # Pabbly only accepts HTTP Basic (API key as username, secret key as password); a
        # regression to Bearer headers would fail against the live API.
        session = MagicMock()
        mock_session.return_value = session
        pabbly._make_session("pabbly-key", "pabbly-secret")
        assert session.auth == ("pabbly-key", "pabbly-secret")
        assert mock_session.call_args.kwargs["redact_values"] == ("pabbly-key", "pabbly-secret")


class TestHttpSampleCapture:
    @parameterized.expand(
        [
            # licenses and coupons bodies carry raw redeemable secrets (license_codes, coupon_code),
            # so their raw responses must stay out of captured HTTP samples; ordinary endpoints keep
            # capture on for diagnostics.
            ("licenses", False),
            ("coupons", False),
            ("customers", True),
        ]
    )
    @patch(f"{pabbly.__name__}._fetch_page")
    @patch(f"{pabbly.__name__}.make_tracked_session")
    def test_capture_disabled_only_for_secret_bearing_endpoints(
        self,
        endpoint: str,
        expected_capture: bool,
        mock_session: MagicMock,
        mock_fetch: MagicMock,
    ) -> None:
        mock_session.return_value = MagicMock()
        mock_fetch.return_value = []

        list(
            get_rows(
                api_key="pabbly-key",
                secret_key="pabbly-secret",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )

        assert mock_session.call_args.kwargs["capture"] is expected_capture


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Pabbly Subscription Billing returned HTTP 500"),
        ]
    )
    @patch(f"{pabbly.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("pabbly-key", "pabbly-secret") == (expected_status, expected_message)

    @patch(f"{pabbly.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("pabbly-key", "pabbly-secret")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Pabbly Subscription Billing API key or secret key"),
            ("forbidden", 403, False, "Invalid Pabbly Subscription Billing API key or secret key"),
            ("server_error", 500, False, "Pabbly Subscription Billing returned HTTP 500"),
        ]
    )
    @patch(f"{pabbly.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("pabbly-key", "pabbly-secret") == (expected_valid, expected_message)


class TestPabblySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = PABBLY_ENDPOINTS[endpoint]
        response = pabbly_source(
            api_key="pabbly-key",
            secret_key="pabbly-secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_children_key_on_parent_and_id(self) -> None:
        # Pabbly doesn't document that child ids are globally unique, so a per-parent id must
        # still be unique table-wide via the composite key.
        for config in PABBLY_ENDPOINTS.values():
            if config.parent:
                assert config.parent_field is not None
                assert config.primary_keys == [config.parent_field, "id"]
                assert "{parent_id}" in config.path
            else:
                assert config.primary_keys == ["id"]
                assert "{parent_id}" not in config.path
