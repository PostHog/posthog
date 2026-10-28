from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumroad import (
    GumroadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad import (
    GumroadResumeConfig,
    _format_gumroad_date,
    _paginator_for,
    _rest_api_client_config,
    check_endpoint_permission,
    get_resource,
    gumroad_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import GUMROAD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.source import GumroadSource


class TestGumroadTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GumroadSource(), GumroadSourceConfig(access_token="gumroad-token"))

    @parameterized.expand(
        [
            # Gumroad rejects anything that isn't YYYY-MM-DD with a 400, so an ISO datetime
            # watermark has to be truncated to its date before it reaches the `after` param.
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01"),
            ("aware_datetime", datetime(2026, 3, 1, 23, 59, 59, tzinfo=UTC), "2026-03-01"),
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("passthrough_string", "1970-01-01", "1970-01-01"),
        ]
    )
    def test_format_gumroad_date(self, _name, value, expected) -> None:
        assert _format_gumroad_date(value) == expected

    @parameterized.expand(
        [
            ("sales", JSONResponseCursorPaginator),
            ("products", JSONResponseCursorPaginator),
            ("payouts", JSONResponseCursorPaginator),
            ("subscribers", JSONResponseCursorPaginator),
            ("product_reviews", JSONResponseCursorPaginator),
            # These return the whole collection in one response and never emit `next_page_key`.
            ("offer_codes", SinglePagePaginator),
            ("variant_categories", SinglePagePaginator),
            ("custom_fields", SinglePagePaginator),
        ]
    )
    def test_paginator_matches_endpoint_pagination(self, endpoint, expected_type) -> None:
        assert isinstance(_paginator_for(GUMROAD_ENDPOINTS[endpoint]), expected_type)

    @parameterized.expand([("sales",), ("payouts",)])
    def test_incremental_resource_uses_after_window(self, endpoint) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        assert incremental["start_param"] == "after"
        assert incremental["cursor_path"] == "created_at"
        assert incremental["convert"] is _format_gumroad_date

    @parameterized.expand([("sales",), ("payouts",), ("products",)])
    def test_full_refresh_resource_sends_no_window(self, endpoint) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("offer_codes", should_use_incremental_field=False)

    @parameterized.expand(
        [
            ("sales", ["id"], "created_at"),
            ("products", ["id"], None),
            ("payouts", ["id"], "created_at"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.rest_api_resource")
    def test_top_level_source_response_shape(self, endpoint, primary_keys, partition_key, _mock) -> None:
        response = gumroad_source(access_token="tok", endpoint=endpoint, team_id=1, job_id="job-1")
        assert response.primary_keys == primary_keys
        # Every Gumroad list endpoint orders created_at DESC with no way to reverse it.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ([partition_key] if partition_key else None)

    @parameterized.expand(
        [
            ("offer_codes", ["product_id", "id"]),
            ("variant_categories", ["product_id", "id"]),
            ("custom_fields", ["product_id", "id"]),
            ("product_reviews", ["product_id", "id"]),
            ("subscribers", ["id"]),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.build_dependent_resource")
    def test_fanout_primary_keys_are_unique_table_wide(self, endpoint, primary_keys, mock_build) -> None:
        # Universal offer codes and global custom fields are repeated under every product they
        # apply to, so the parent product id has to be part of the key.
        mock_build.return_value = iter([])
        response = gumroad_source(access_token="tok", endpoint=endpoint, team_id=1, job_id="job-1")
        assert response.primary_keys == primary_keys

    def test_resume_state_seeds_paginator_cursor(self) -> None:
        result = self._driver().run(
            "sales",
            [ScriptedResponse(json={"sales": [{"id": "sale-9"}]})],
            resume_state=GumroadResumeConfig(page_key="cursor-9"),
        )

        assert result.raised is None
        assert result.params("page_key") == ["cursor-9"]
        assert result.rows == [{"id": "sale-9"}]

    @parameterized.expand(
        [
            ("missing_cursor", {"sales": [{"id": "sale-2"}]}),
            ("null_cursor", {"sales": [{"id": "sale-2"}], "next_page_key": None}),
            ("empty_cursor", {"sales": [{"id": "sale-2"}], "next_page_key": ""}),
        ]
    )
    def test_resume_hook_saves_only_a_real_next_cursor(self, _name, last_page) -> None:
        result = self._driver().run(
            "sales",
            [
                ScriptedResponse(json={"sales": [{"id": "sale-1"}], "next_page_key": "cursor-3"}),
                ScriptedResponse(json=last_page),
            ],
        )

        assert result.raised is None
        assert result.params("page_key") == [None, "cursor-3"]
        assert result.rows == [{"id": "sale-1"}, {"id": "sale-2"}]
        assert result.saved_states == [GumroadResumeConfig(page_key="cursor-3")]

    @parameterized.expand(
        [
            (
                "stops_at_first_unavailable_year_below_last_year",
                [404, 200, 200, 404],
                [2025, 2024],
                None,
            ),
            # Gumroad's clock can still be in the previous year, so last year is not yet available.
            ("skips_unavailable_last_year", [404, 404, 200, 404], [2024], None),
            ("account_created_this_year", [404, 404, 404], [], None),
            ("tax_center_disabled", [403], [], "403 Client Error: Forbidden for url"),
        ]
    )
    @time_machine.travel(datetime(2026, 1, 1, 3, 0, tzinfo=UTC), tick=False)
    def test_earnings_walks_back_through_available_tax_years(
        self, _name, statuses, expected_years, expected_error
    ) -> None:
        script = [
            ScriptedResponse(status=status, json={"success": True, "year": 2026 - index, "net_cents": 100})
            if status == 200
            else ScriptedResponse(status=status, json={"success": False})
            for index, status in enumerate(statuses)
        ]

        result = self._driver().run("earnings", script)

        assert result.params("year") == [str(2026 - index) for index in range(len(statuses))]
        assert [row["year"] for row in result.rows] == expected_years
        assert all("success" not in row for row in result.rows)
        if expected_error is None:
            assert result.raised is None
        else:
            assert expected_error in str(result.raised)

    def test_workflow_emails_fan_out_reads_steps_from_each_workflow(self) -> None:
        result = self._driver().run(
            "workflow_emails",
            [
                ScriptedResponse(json={"success": True, "workflows": [{"id": "wf-1"}, {"id": "wf-2"}]}),
                ScriptedResponse(
                    json={"success": True, "workflow": {"id": "wf-1", "emails": [{"id": "e-1", "sent_count": 3}]}}
                ),
                ScriptedResponse(json={"success": True, "workflow": {"id": "wf-2", "emails": []}}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v2/workflows", "/v2/workflows/wf-1", "/v2/workflows/wf-2"]
        assert result.rows == [{"id": "e-1", "sent_count": 3, "workflow_id": "wf-1"}]

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "rejected the access token"),
            (403, False, "rejected the access token"),
            (500, False, "unexpected status code"),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("gumroad-token")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        # `/v2/user` is readable by every scope Gumroad issues, so a failure here is the token
        # itself rather than a missing scope.
        assert network.requests_log[0].url == "https://api.gumroad.com/v2/user"
        assert network.requests_log[0].headers["authorization"] == "Bearer gumroad-token"
        # The probe must refuse redirects so a 3xx can't replay the bearer token off-host.
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("gumroad-token",)

    @parameterized.expand(
        [
            (200, True),
            (403, False),
            # A 401 means the whole token is bad, and a 500 is transient — neither is a scope
            # problem, so neither should be reported to the user as one.
            (401, True),
            (500, True),
        ]
    )
    def test_check_endpoint_permission_only_treats_403_as_denial(self, status, expected) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_endpoint_permission("gumroad-token", "/v2/sales") is expected
        assert {request.path for request in network.requests_log} == {"/v2/sales"}

    def test_probe_transport_error_does_not_leak_out(self) -> None:
        # A DNS/connection failure isn't a permission problem, so it must not raise out of the
        # schema picker / source creation path: the endpoint stays "reachable" and validation
        # reports a connectivity problem rather than blaming the token.
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert check_endpoint_permission("gumroad-token", "/v2/sales") is True
            is_valid, message = validate_credentials("gumroad-token")
        assert is_valid is False
        assert message is not None and "reach Gumroad" in message
        assert {request.path for request in network.requests_log} == {"/v2/sales", "/v2/user"}

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Gumroad host would otherwise replay the bearer token.
        config = _rest_api_client_config("gumroad-token")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "gumroad-token"}
        assert config["base_url"] == "https://api.gumroad.com"
