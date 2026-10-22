from base64 import b64encode
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pabblysubscriptionsbilling import (
    PabblySubscriptionsBillingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.pabbly_subscriptions_billing import (
    PAGE_SIZE,
    PabblyResumeConfig,
    PabblyRetryableError,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.settings import (
    ENDPOINTS,
    PABBLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.source import (
    PabblySubscriptionsBillingSource,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        PabblySubscriptionsBillingSource(),
        PabblySubscriptionsBillingSourceConfig(api_key="pabbly-key", secret_key="pabbly-secret"),
    )


def _page(rows: Any) -> ScriptedResponse:
    return ScriptedResponse(json={"status": "success", "data": rows})


def _full_page(prefix: str) -> list[dict[str, str]]:
    return [{"id": f"{prefix}{i}"} for i in range(PAGE_SIZE)]


class TestGetRowsTopLevel:
    def test_single_short_page_yields_and_stops(self) -> None:
        result = _driver().run("customers", [_page([{"id": "1"}, {"id": "2"}])])
        assert result.raised is None
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert result.paths == ["/api/v1/customers"]
        # The list ended on the first page, so no resume state is persisted.
        assert result.saved_states == []

    def test_follows_page_pagination_until_short_page(self) -> None:
        result = _driver().run("customers", [_page(_full_page("a")), _page([{"id": "last"}])])
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["1", "2"]
        # State is saved after the first full page (pointing at the next page), then we stop.
        assert result.saved_states == [PabblyResumeConfig(page=2)]
        assert result.committed_states == [PabblyResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        # Pages 1 and 2 must never be re-fetched on resume.
        result = _driver().run("customers", [_page([{"id": "5"}])], resume_state=PabblyResumeConfig(page=3))
        assert result.raised is None
        assert result.rows == [{"id": "5"}]
        assert result.params("page") == ["3"]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("customers", [_page([])])
        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []


class TestGetRowsFanOut:
    def test_fetches_children_for_each_parent_and_injects_parent_id(self) -> None:
        result = _driver().run(
            "transactions",
            [
                _page([{"id": "cus_1"}, {"id": "cus_2"}]),
                _page([{"id": "tra_1"}]),
                # The API already stamps customer_id on this row; injection must not overwrite it.
                _page([{"id": "tra_2", "customer_id": "already-set"}]),
            ],
        )
        assert result.raised is None
        assert result.paths == [
            "/api/v1/customers",
            "/api/v1/transactions/cus_1",
            "/api/v1/transactions/cus_2",
        ]
        assert result.rows == [
            {"id": "tra_1", "customer_id": "cus_1"},
            {"id": "tra_2", "customer_id": "already-set"},
        ]
        # A single short parent page means the whole sync fit in one pass — no state persisted.
        assert result.saved_states == []

    def test_paginates_children_within_a_parent(self) -> None:
        result = _driver().run(
            "addons", [_page([{"id": "pro_1"}]), _page(_full_page("add_a")), _page([{"id": "add_last"}])]
        )
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert all(row["product_id"] == "pro_1" for row in result.rows)
        assert result.paths == ["/api/v1/products", "/api/v1/addons/pro_1", "/api/v1/addons/pro_1"]
        assert result.params("page") == ["1", "1", "2"]

    def test_saves_state_after_each_full_parent_page(self) -> None:
        result = _driver().run(
            "refunds",
            [
                _page(_full_page("cus_a")),
                *[_page([]) for _ in range(PAGE_SIZE)],
                _page([{"id": "cus_last"}]),
                _page([]),
            ],
        )
        assert result.raised is None
        assert result.rows == []
        assert result.paths[0] == "/api/v1/customers"
        assert result.paths[-2:] == ["/api/v1/customers", "/api/v1/refund/cus_last"]
        assert result.params("page")[0] == "1"
        assert result.params("page")[-2] == "2"
        # Resume state advances to parent page 2 only once every child of page 1 was yielded.
        assert result.saved_states == [PabblyResumeConfig(page=2)]

    def test_resumes_from_saved_parent_page(self) -> None:
        # Parent page 1 must never be re-fetched on resume.
        result = _driver().run(
            "payment_methods",
            [_page([{"id": "cus_1"}]), _page([{"id": "pay_1"}])],
            resume_state=PabblyResumeConfig(page=2),
        )
        assert result.raised is None
        assert result.rows == [{"id": "pay_1", "customer_id": "cus_1"}]
        assert result.paths == ["/api/v1/customers", "/api/v1/paymentmethods/cus_1"]
        assert result.params("page") == ["2", "1"]

    def test_parent_row_without_an_id_fails_fast(self) -> None:
        # A parent row missing its primary key must raise rather than silently drop its children.
        result = _driver().run("coupons", [_page([{"name": "no id"}])])
        assert isinstance(result.raised, KeyError)
        assert result.paths == ["/api/v1/products"]


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("customers", always(ScriptedResponse(status=status)))
        assert isinstance(result.raised, PabblyRetryableError)
        assert set(result.paths) == {"/api/v1/customers"}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("customers", [ScriptedResponse(status=status)])
        assert isinstance(result.raised, requests.HTTPError)

    def test_400_raises_when_endpoint_does_not_ignore_no_data_errors(self) -> None:
        result = _driver().run("customers", [ScriptedResponse(status=400)])
        assert isinstance(result.raised, requests.HTTPError)

    def test_400_is_empty_page_when_endpoint_ignores_no_data_errors(self) -> None:
        result = _driver().run("addons", [_page([{"id": "pro_1"}]), ScriptedResponse(status=400)])
        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/v1/products", "/api/v1/addons/pro_1"]

    def test_success_returns_data_rows(self) -> None:
        result = _driver().run("customers", [_page([{"id": "1"}])])
        assert result.raised is None
        assert result.rows == [{"id": "1"}]

    def test_dict_data_is_wrapped_into_a_single_row(self) -> None:
        result = _driver().run("customers", [_page({"id": "1"})])
        assert result.raised is None
        assert result.rows == [{"id": "1"}]

    def test_missing_data_key_is_empty_page(self) -> None:
        result = _driver().run("customers", [ScriptedResponse(json={"status": "success"})])
        assert result.raised is None
        assert result.rows == []

    def test_non_dict_body_is_retryable(self) -> None:
        result = _driver().run("customers", always(ScriptedResponse(json=[{"id": "1"}])))
        assert isinstance(result.raised, PabblyRetryableError)

    @parameterized.expand(
        [
            ("no_transaction_found", "No transaction found"),
            ("no_data_found", "No data found"),
        ]
    )
    def test_no_data_error_envelope_is_empty_page(self, _name: str, message: str) -> None:
        # Pabbly can answer "resource has no rows" as an HTTP 200 error envelope.
        result = _driver().run(
            "refunds", [_page([{"id": "cus_1"}]), ScriptedResponse(json={"status": "error", "message": message})]
        )
        assert result.raised is None
        assert result.rows == []

    def test_other_error_envelope_raises(self) -> None:
        result = _driver().run("customers", [ScriptedResponse(json={"status": "error", "message": "Invalid user api"})])
        assert isinstance(result.raised, ValueError)
        assert "Invalid user api" in str(result.raised)

    def test_sends_page_and_limit_params(self) -> None:
        result = _driver().run("subscriptions", [_page([])], resume_state=PabblyResumeConfig(page=4))
        assert result.raised is None
        assert result.params("page") == ["4"]
        assert result.params("limit") == [str(PAGE_SIZE)]


class TestMakeSession:
    def test_authenticates_with_http_basic(self) -> None:
        # Pabbly only accepts HTTP Basic (API key as username, secret key as password); a
        # regression to Bearer headers would fail against the live API.
        result = _driver().run("customers", [_page([])])
        expected = b64encode(b"pabbly-key:pabbly-secret").decode()
        assert result.raised is None
        assert result.requests[0].headers["authorization"] == f"Basic {expected}"
        assert result.session_options[0]["redact_values"] == ("pabbly-key", "pabbly-secret")


class TestHttpSampleCapture:
    @parameterized.expand(
        [
            # Capture is opt-in: only endpoints limited to product/plan catalog metadata may write raw
            # bodies to HTTP samples. Everything carrying customer PII, payment data, redeemable
            # secrets, or bearer URLs the scrubbers can't recognise must stay out of captured samples.
            ("products", True),
            ("multiplans", True),
            ("addons", True),
            ("addon_list_category", True),
            ("customers", False),
            ("subscriptions", False),
            ("invoices", False),
            ("payment_gateways", False),
            ("payment_methods", False),
            ("refunds", False),
            ("transactions", False),
            ("licenses", False),
            ("coupons", False),
        ]
    )
    def test_capture_enabled_only_for_catalog_metadata_endpoints(
        self,
        endpoint: str,
        expected_capture: bool,
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        assert result.session_options[0]["capture"] is expected_capture

    def test_credential_probe_never_captures(self) -> None:
        # The probe hits /customers, so a captured sample would persist a raw customer record;
        # credential validation must run with capture off.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert check_access("pabbly-key", "pabbly-secret") == (200, None)
        assert network.session_options[0]["capture"] is False
        assert network.requests_log[0].path == "/api/v1/customers"


class TestCheckAccess:
    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        _ok: bool,
        expected_status: int,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access("pabbly-key", "pabbly-secret") == (expected_status, expected_message)
        assert network.requests_log[0].path == "/api/v1/customers"
        assert network.requests_log[0].param("page") == "1"
        assert network.requests_log[0].param("limit") == "1"


class TestPabblySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = PABBLY_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        response = result.response
        assert response is not None
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
