from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lago import LagoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lago import lago as lago_module
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import (
    LagoHostNotAllowedError,
    LagoResumeConfig,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.source import LagoSource


def _page(
    rows: list[dict[str, Any]],
    *,
    total_pages: int = 1,
    next_page: int | None = None,
    data_key: str = "customers",
) -> ScriptedResponse:
    return ScriptedResponse(json={"meta": {"total_pages": total_pages, "next_page": next_page}, data_key: rows})


def _driver(api_url: str | None = None) -> SourceDriver:
    return SourceDriver(LagoSource(), LagoSourceConfig(api_key="key", api_url=api_url))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://api.getlago.com/api/v1"),
            ("", "https://api.getlago.com/api/v1"),
            ("   ", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/api/v1", "https://api.getlago.com/api/v1"),
            ("billing.example.com", "https://billing.example.com/api/v1"),
            ("http://billing.example.com/", "http://billing.example.com/api/v1"),
            ("https://billing.example.com/api/v2", "https://billing.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestValidateCredentials:
    def test_invalid_key(self):
        with scripted_network([ScriptedResponse(status=401)]) as network:
            valid, msg = validate_credentials(None, "key")

        assert valid is False
        assert msg == "Invalid Lago API key"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials(None, "key", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials(None, "key", schema_name="invoices")

        assert valid is False
        assert msg is not None

    def test_404_returns_actionable_message_not_raw_body(self):
        # A 404 used to surface Lago's bare "Not Found" body verbatim, which tells the user nothing.
        with scripted_network([ScriptedResponse(status=404, json={"error": "Not Found"})]):
            valid, msg = validate_credentials(None, "key")

        assert valid is False
        assert msg is not None
        assert msg != "Not Found"
        assert "404" in msg

    def test_other_error_status_does_not_leak_raw_body(self):
        with scripted_network(always(ScriptedResponse(status=500, json={"error": "Internal"}))):
            valid, msg = validate_credentials(None, "key")

        assert valid is False
        assert msg is not None
        assert "Internal" not in msg
        assert "500" in msg

    def test_rejects_redirect_response(self):
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/api/v1/customers"})]
        ) as network:
            valid, msg = validate_credentials(None, "key")

        assert valid is False
        assert msg == lago_module.HOST_NOT_ALLOWED_ERROR
        assert len(network.requests_log) == 1

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "key", team_id=99)

        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []

    def test_probe_hits_configured_host(self):
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("https://billing.example.com", "key")

        assert network.requests_log[0].path == "/api/v1/customers"
        assert network.requests_log[0].origin == "https://billing.example.com"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].param("page") == "1"


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("customers", "/api/v1/customers"),
            ("taxes", "/api/v1/taxes"),
            ("payment_requests", "/api/v1/payment_requests"),
            ("payment_receipts", "/api/v1/payment_receipts"),
        ],
    )
    def test_paginates_and_progresses_page(self, endpoint, path):
        result = _driver().run(
            endpoint,
            [
                _page([{"lago_id": "1"}, {"lago_id": "2"}], total_pages=2, next_page=2, data_key=endpoint),
                _page([{"lago_id": "3"}], total_pages=2, data_key=endpoint),
            ],
        )

        assert result.raised is None
        assert [row["lago_id"] for row in result.rows] == ["1", "2", "3"]
        assert result.paths == [path, path]
        # First request page=1, second request page=2, both carry per_page.
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == ["100", "100"]

    @pytest.mark.parametrize(
        "endpoint, path, data_key, row",
        [
            ("billing_entities", "/api/v1/billing_entities", "billing_entities", {"lago_id": "be1", "code": "acme"}),
            (
                "analytics_mrr",
                "/api/v1/analytics/mrr",
                "mrrs",
                {"month": "2024-01-01T00:00:00.000Z", "amount_cents": None, "currency": None},
            ),
            (
                "analytics_gross_revenue",
                "/api/v1/analytics/gross_revenue",
                "gross_revenues",
                {"month": "2024-01-01T00:00:00.000Z", "amount_cents": 1200, "currency": "EUR"},
            ),
            (
                "analytics_invoice_collection",
                "/api/v1/analytics/invoice_collection",
                "invoice_collections",
                {"month": "2024-01-01T00:00:00.000Z", "payment_status": "succeeded", "invoices_count": 3},
            ),
            (
                "analytics_invoiced_usage",
                "/api/v1/analytics/invoiced_usage",
                "invoiced_usages",
                {"month": "2024-01-01T00:00:00.000Z", "code": "api_calls", "currency": "USD"},
            ),
            (
                "analytics_overdue_balance",
                "/api/v1/analytics/overdue_balance",
                "overdue_balances",
                {"month": "2024-01-01T00:00:00.000Z", "lago_invoice_ids": ["inv-1"], "currency": "USD"},
            ),
        ],
    )
    def test_unpaginated_endpoint_makes_one_request_without_page_params(self, endpoint, path, data_key, row):
        # These bodies carry no `meta`, so page-number pagination must not apply.
        result = _driver().run(endpoint, [ScriptedResponse(json={data_key: [row, row]})])

        assert result.raised is None
        assert result.rows == [row, row]
        assert result.paths == [path]
        assert result.params("page") == [None]
        assert result.params("per_page") == [None]

    def test_resumes_from_saved_state(self):
        result = _driver().run(
            "customers", [_page([{"lago_id": "9"}], total_pages=3)], resume_state=LagoResumeConfig(next_page=3)
        )

        assert result.raised is None
        assert result.params("page") == ["3"]
        assert [row["lago_id"] for row in result.rows] == ["9"]


class TestRedirectAndHostGuards:
    def test_rejects_redirect(self):
        result = _driver().run(
            "customers",
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/api/v1/customers"})],
        )

        # allow_redirects=False in the client config surfaces a 3xx as a loud, non-retryable error.
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised)

    def test_does_not_follow_redirects(self):
        result = _driver().run(
            "customers",
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/api/v1/customers"})],
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/v1/customers"]

    def test_raises_when_host_not_allowed(self):
        with mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("customers", [])

        assert isinstance(result.raised, LagoHostNotAllowedError)
        # The SSRF pre-check fires before any request leaves the process.
        assert result.requests == []


class TestFanout:
    def test_charges_walk_every_plan_and_child_page(self):
        result = _driver().run(
            "charges",
            [
                _page(
                    [{"lago_id": "p1", "code": "pro/annual"}, {"lago_id": "p2", "code": "basic"}],
                    data_key="plans",
                ),
                _page([{"lago_id": "c1"}], total_pages=2, next_page=2, data_key="charges"),
                _page([{"lago_id": "c2"}], total_pages=2, data_key="charges"),
                _page([{"lago_id": "c3"}], data_key="charges"),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/plans",
            # A user-defined plan code is percent-encoded so it stays one path segment.
            "/api/v1/plans/pro%2Fannual/charges",
            "/api/v1/plans/pro%2Fannual/charges",
            "/api/v1/plans/basic/charges",
        ]
        assert result.params("page") == ["1", "1", "2", "1"]
        assert [(row["lago_id"], row["lago_plan_id"], row["plan_code"]) for row in result.rows] == [
            ("c1", "p1", "pro/annual"),
            ("c2", "p1", "pro/annual"),
            ("c3", "p2", "basic"),
        ]
        assert all("_path_code" not in row for row in result.rows)
        assert result.saved_states and all(
            state.fanout_state is not None and state.next_page is None for state in result.saved_states
        )
