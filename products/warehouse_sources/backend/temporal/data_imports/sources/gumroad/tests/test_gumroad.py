from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
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


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _response(body: dict[str, Any]) -> Mock:
    response = Mock()
    response.json.return_value = body
    return response


class TestGumroadTransport:
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

    def test_page_key_paginator_round_trips_cursor(self) -> None:
        resource = cast(dict[str, Any], get_resource("sales", should_use_incremental_field=False))
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, JSONResponseCursorPaginator)

        request = Mock()
        request.params = {}
        paginator.update_state(_response({"success": True, "sales": [], "next_page_key": "cursor-2"}), data=[{}])
        assert paginator.has_next_page is True
        paginator.update_request(request)
        assert request.params["page_key"] == "cursor-2"

        # A response without `next_page_key` is the last page.
        paginator.update_state(_response({"success": True, "sales": []}), data=[{}])
        assert paginator.has_next_page is False

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

    def test_payouts_request_excludes_upcoming(self) -> None:
        # Upcoming payouts are returned with a null id, which would break the primary key.
        resource = cast(dict[str, Any], get_resource("payouts", should_use_incremental_field=False))
        assert resource["endpoint"]["params"] == {"include_upcoming": "false"}

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

    def test_products_has_no_incremental_window_even_when_requested(self) -> None:
        # The product payload carries no timestamp, so there is nothing to filter on.
        resource = cast(dict[str, Any], get_resource("products", should_use_incremental_field=True))
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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_offer_codes_fanout_row_carries_product_id(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("products", [{"id": "prod_1", "name": "Product"}]),
            _FakeDltResource("offer_codes", [{"id": "code_1", "name": "LAUNCH", "_products_id": "prod_1"}]),
        ]

        response = gumroad_source(access_token="tok", endpoint="offer_codes", team_id=1, job_id="job-1")

        rows = list(cast(Any, response.items()))
        assert rows == [{"id": "code_1", "name": "LAUNCH", "product_id": "prod_1"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.build_dependent_resource")
    def test_fanout_wiring(self, mock_build) -> None:
        mock_build.return_value = iter([])

        gumroad_source(access_token="tok", endpoint="subscribers", team_id=1, job_id="job-1")

        kwargs = mock_build.call_args.kwargs
        # Gumroad list endpoints take no page-size parameter; sending one would be undocumented.
        assert kwargs["page_size_param"] is None
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "products"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "subscribers"
        # Without `paginated=true` the subscribers endpoint returns the entire collection in one
        # response and never emits a cursor.
        assert kwargs["fanout"].child_params == {"paginated": "true"}
        assert kwargs["fanout"].parent_name == "products"
        assert kwargs["fanout"].resolve_param == "product_id"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.rest_api_resource")
    def test_resume_state_seeds_paginator_cursor(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = GumroadResumeConfig(page_key="cursor-9")

        gumroad_source(
            access_token="tok",
            endpoint="sales",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "cursor-9"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.rest_api_resource")
    def test_resume_hook_saves_only_a_real_next_cursor(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        gumroad_source(
            access_token="tok",
            endpoint="sales",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"cursor": "cursor-3"})
        assert manager.save_state.call_args.args[0] == GumroadResumeConfig(page_key="cursor-3")

        manager.save_state.reset_mock()
        resume_hook(None)
        resume_hook({})
        resume_hook({"cursor": None})
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "rejected the access token"),
            (403, False, "rejected the access token"),
            (500, False, "unexpected status code"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_valid, message_fragment, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        is_valid, message = validate_credentials("gumroad-token")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        call = mock_session.return_value.get.call_args
        # `/v2/user` is readable by every scope Gumroad issues, so a failure here is the token
        # itself rather than a missing scope.
        assert call.args[0] == "https://api.gumroad.com/v2/user"
        assert call.kwargs["headers"]["Authorization"] == "Bearer gumroad-token"
        # The probe must refuse redirects so a 3xx can't replay the bearer token off-host.
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("gumroad-token",)

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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.make_tracked_session")
    def test_check_endpoint_permission_only_treats_403_as_denial(self, status, expected, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)
        assert check_endpoint_permission("gumroad-token", "/v2/sales") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad.make_tracked_session")
    def test_probe_transport_error_does_not_leak_out(self, mock_session) -> None:
        # A DNS/connection failure isn't a permission problem, so it must not raise out of the
        # schema picker / source creation path: the endpoint stays "reachable" and validation
        # reports a connectivity problem rather than blaming the token.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert check_endpoint_permission("gumroad-token", "/v2/sales") is True

        is_valid, message = validate_credentials("gumroad-token")
        assert is_valid is False
        assert message is not None and "reach Gumroad" in message

    def test_rest_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off the Gumroad host would otherwise replay the bearer token.
        config = _rest_api_client_config("gumroad-token")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "gumroad-token"}
        assert config["base_url"] == "https://api.gumroad.com"
