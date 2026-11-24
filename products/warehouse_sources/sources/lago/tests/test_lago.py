from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.lago import lago as lago_module
from products.warehouse_sources.sources.lago._config import LagoSourceConfig
from products.warehouse_sources.sources.lago.lago import (
    LagoHostNotAllowedError,
    LagoResumeConfig,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.sources.lago.source import LagoSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


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

    @parameterized.expand(
        [
            (
                "current_usage",
                "customer_current_usage",
                [
                    ScriptedResponse(json={"customer_usage": {"amount_cents": 120, "currency": "EUR"}}),
                    ScriptedResponse(json={"customer_usage": {"amount_cents": 0, "currency": "EUR"}}),
                ],
                [
                    "/api/v1/customers/cus%2F1/current_usage",
                    "/api/v1/customers/cus-2/current_usage",
                ],
                [None, None],
                [
                    {"amount_cents": 120, "lago_subscription_id": "s1", "external_subscription_id": "sub 1"},
                    {"amount_cents": 0, "lago_subscription_id": "s2", "external_subscription_id": "sub-2"},
                ],
            ),
            (
                "past_usage_pages",
                "customer_past_usage",
                [
                    _page(
                        [{"from_datetime": "2024-01-01T00:00:00Z"}],
                        total_pages=2,
                        next_page=2,
                        data_key="usage_periods",
                    ),
                    _page([{"from_datetime": "2024-02-01T00:00:00Z"}], total_pages=2, data_key="usage_periods"),
                    _page([{"from_datetime": "2024-01-01T00:00:00Z"}], data_key="usage_periods"),
                ],
                [
                    "/api/v1/customers/cus%2F1/past_usage",
                    "/api/v1/customers/cus%2F1/past_usage",
                    "/api/v1/customers/cus-2/past_usage",
                ],
                ["1", "2", "1"],
                [
                    {"from_datetime": "2024-01-01T00:00:00Z", "lago_subscription_id": "s1"},
                    {"from_datetime": "2024-02-01T00:00:00Z", "lago_subscription_id": "s1"},
                    {"from_datetime": "2024-01-01T00:00:00Z", "lago_subscription_id": "s2"},
                ],
            ),
            (
                "lifetime_usage_skips_404",
                "subscription_lifetime_usage",
                [
                    ScriptedResponse(
                        status=404, json={"status": 404, "error": "Not Found", "code": "lifetime_usage_not_found"}
                    ),
                    ScriptedResponse(
                        json={
                            "lifetime_usage": {
                                "lago_id": "lu2",
                                "lago_subscription_id": "s2",
                                "external_subscription_id": "sub-2",
                                "current_usage_amount_cents": 500,
                            }
                        }
                    ),
                ],
                [
                    "/api/v1/subscriptions/sub%201/lifetime_usage",
                    "/api/v1/subscriptions/sub-2/lifetime_usage",
                ],
                [None, None],
                [
                    {
                        "lago_id": "lu2",
                        "lago_subscription_id": "s2",
                        "external_subscription_id": "sub-2",
                        "external_customer_id": "cus-2",
                    }
                ],
            ),
        ]
    )
    def test_subscription_usage_fans_out_over_each_subscription(
        self, _name, endpoint, child_responses, child_paths, child_pages, expected_rows
    ):
        subscriptions = _page(
            [
                {"lago_id": "s1", "external_id": "sub 1", "external_customer_id": "cus/1"},
                {"lago_id": "s2", "external_id": "sub-2", "external_customer_id": "cus-2"},
            ],
            data_key="subscriptions",
        )
        result = _driver().run(endpoint, [subscriptions, *child_responses])

        assert result.raised is None
        assert result.paths == ["/api/v1/subscriptions", *child_paths]
        # The customer id rides in the path and the subscription id in the query, both encoded once.
        expected_subscription_ids = [
            "sub 1" if "cus%2F1" in path or "sub%201" in path else "sub-2" for path in child_paths
        ]
        if endpoint != "subscription_lifetime_usage":
            assert result.params("external_subscription_id")[1:] == expected_subscription_ids
        assert result.params("page")[1:] == child_pages
        assert [{key: row.get(key) for key in expected} for row, expected in zip(result.rows, expected_rows)] == (
            expected_rows
        )
        assert len(result.rows) == len(expected_rows)
        assert all(not key.startswith("_") for row in result.rows for key in row)

    def test_plan_entitlements_read_each_plan_once(self):
        result = _driver().run(
            "plan_entitlements",
            [
                _page([{"lago_id": "p1", "code": "pro/annual"}, {"lago_id": "p2", "code": "basic"}], data_key="plans"),
                ScriptedResponse(json={"entitlements": [{"code": "seats", "privileges": []}, {"code": "sso"}]}),
                ScriptedResponse(json={"entitlements": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/plans",
            "/api/v1/plans/pro%2Fannual/entitlements",
            "/api/v1/plans/basic/entitlements",
        ]
        # The entitlement body has no `meta`, so a second page must never be requested.
        assert result.params("page")[1:] == [None, None]
        assert [(row["lago_plan_id"], row["plan_code"], row["code"]) for row in result.rows] == [
            ("p1", "pro/annual", "seats"),
            ("p1", "pro/annual", "sso"),
        ]


class TestActivityLogsIncremental:
    @parameterized.expand(
        [
            ("full_refresh", {}, None),
            ("incremental_first_sync", {"should_use_incremental_field": True}, None),
            (
                "incremental_with_watermark",
                {
                    "should_use_incremental_field": True,
                    "incremental_field": "logged_at",
                    "db_incremental_field_last_value": datetime(2024, 3, 1, 12, 30, tzinfo=UTC),
                },
                "2024-03-01T12:30:00Z",
            ),
        ]
    )
    def test_from_date_is_sent_only_with_a_watermark(self, _name, inputs, expected_from_date):
        result = _driver().run(
            "activity_logs",
            [
                _page([{"activity_id": "a2"}], total_pages=2, next_page=2, data_key="activity_logs"),
                _page([{"activity_id": "a1"}], total_pages=2, data_key="activity_logs"),
            ],
            **inputs,
        )

        assert result.raised is None
        assert [row["activity_id"] for row in result.rows] == ["a2", "a1"]
        # Every page keeps the filter, so later pages never walk back past the watermark.
        assert result.params("from_date") == [expected_from_date, expected_from_date]
        assert result.params("page") == ["1", "2"]
        # Lago returns activity logs newest first, so the read declares no ascending order.
        assert result.response is not None and result.response.sort_mode is None
