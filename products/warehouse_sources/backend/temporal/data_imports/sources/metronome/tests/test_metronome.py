from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome import (
    MetronomeCursorPaginator,
    MetronomeResumeConfig,
    _format_rfc3339,
    _paginator_for,
    get_resource,
    metronome_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.settings import METRONOME_ENDPOINTS

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome"


def _response(body: dict[str, Any]) -> Mock:
    response = Mock()
    response.json.return_value = body
    return response


def _request(params: dict[str, Any] | None = None) -> Mock:
    request = Mock()
    request.params = params if params is not None else {}
    return request


class TestMetronomePaginator:
    def test_follows_next_page_and_stops_when_it_goes_null(self) -> None:
        paginator = MetronomeCursorPaginator()
        request = _request()

        paginator.update_state(_response({"data": [{"id": "a"}], "next_page": "cursor-2"}), data=[{"id": "a"}])
        assert paginator.has_next_page is True
        paginator.update_request(request)
        assert request.params["next_page"] == "cursor-2"

        # Metronome sends an explicit null once the collection is exhausted.
        paginator.update_state(_response({"data": [{"id": "b"}], "next_page": None}), data=[{"id": "b"}])
        assert paginator.has_next_page is False

    def test_stops_on_an_empty_page_that_still_carries_a_cursor(self) -> None:
        # `GET /v1/auditLogs` always returns a cursor, so a cursor-only stop condition would loop
        # forever once the account has no newer entries.
        paginator = MetronomeCursorPaginator()

        paginator.update_state(_response({"data": [], "next_page": "cursor-2"}), data=[])

        assert paginator.has_next_page is False

    def test_time_window_only_rides_the_request_without_a_cursor(self) -> None:
        # Metronome rejects `starting_on` when a cursor is also sent.
        paginator = MetronomeCursorPaginator(first_page_only_params=("starting_on",))
        request = _request({"starting_on": "2026-01-01T00:00:00Z", "sort": "date_asc"})

        paginator.init_request(request)
        assert request.params["starting_on"] == "2026-01-01T00:00:00Z"

        paginator.update_state(_response({"data": [{"id": "a"}], "next_page": "cursor-2"}), data=[{"id": "a"}])
        paginator.update_request(request)

        assert "starting_on" not in request.params
        assert request.params["next_page"] == "cursor-2"
        assert request.params["sort"] == "date_asc"

    def test_resumed_run_drops_the_time_window_from_its_first_request(self) -> None:
        # A resumed run starts mid-pagination, so even its first request carries a cursor.
        paginator = MetronomeCursorPaginator(first_page_only_params=("starting_on",))
        paginator.set_resume_state({"cursor": "cursor-9"})
        request = _request({"starting_on": "2026-01-01T00:00:00Z"})

        paginator.init_request(request)

        assert request.params == {"next_page": "cursor-9"}

    def test_contracts_endpoint_is_not_paginated(self) -> None:
        # `POST /v2/contracts/list` returns every contract for the customer in one response.
        assert isinstance(_paginator_for(METRONOME_ENDPOINTS["contracts"]), SinglePagePaginator)


class TestMetronomeResources:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 23, 59, 59, tzinfo=UTC), "2026-03-01T23:59:59Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_rfc3339(self, _name, value, expected) -> None:
        assert _format_rfc3339(value) == expected

    def test_audit_logs_incremental_resource_uses_starting_on(self) -> None:
        resource = cast(dict[str, Any], get_resource("audit_logs", should_use_incremental_field=True))

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        assert incremental["start_param"] == "starting_on"
        assert incremental["cursor_path"] == "timestamp"
        assert incremental["convert"] is _format_rfc3339

    def test_audit_logs_full_refresh_sends_no_window(self) -> None:
        resource = cast(dict[str, Any], get_resource("audit_logs", should_use_incremental_field=False))

        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]
        assert "starting_on" not in resource["endpoint"]["params"]

    @parameterized.expand([("customers",), ("products",), ("packages",), ("billable_metrics",)])
    def test_endpoints_without_a_time_filter_never_go_incremental(self, endpoint) -> None:
        # Metronome exposes no created/updated filter on these, so an "incremental" sync would
        # still fetch every page and cost the same as a full refresh.
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=True))

        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

    @parameterized.expand(
        [
            ("products", {"archive_filter": "ALL"}),
            ("packages", {"archive_filter": "ALL"}),
            # The rate cards endpoint takes no filters but still expects a JSON document.
            ("rate_cards", {}),
        ]
    )
    def test_post_endpoints_send_filters_in_the_body_and_paginate_in_the_query(self, endpoint, expected_body) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=False))

        assert resource["endpoint"]["method"] == "post"
        assert resource["endpoint"]["json"] == expected_body
        assert resource["endpoint"]["params"] == {"limit": 100}

    @parameterized.expand([("invoices",), ("contracts",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint, should_use_incremental_field=False)


class TestMetronomeSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "created_at"),
            ("audit_logs", ["id"], "timestamp"),
            ("pricing_units", ["id"], None),
        ]
    )
    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_top_level_response_shape(self, endpoint, primary_keys, partition_key, _mock) -> None:
        response = metronome_source(api_key="tok", endpoint=endpoint, team_id=1, job_id="job-1")

        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)

    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_resume_state_seeds_the_paginator_cursor(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = MetronomeResumeConfig(next_page="cursor-9")

        metronome_source(
            api_key="tok", endpoint="customers", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "cursor-9"}

    @patch(f"{TRANSPORT}.build_dependent_resource")
    def test_invoices_fan_out_over_customers(self, mock_build) -> None:
        mock_build.return_value = iter([])

        metronome_source(api_key="tok", endpoint="invoices", team_id=1, job_id="job-1")

        kwargs = mock_build.call_args.kwargs
        assert kwargs["fanout"].parent_name == "customers"
        assert kwargs["fanout"].resolve_param == "customer_id"
        # The invoice payload already carries `customer_id`, so nothing is copied down.
        assert kwargs["fanout"].include_from_parent == []
        assert kwargs["fanout"].child_params == {"sort": "date_asc"}
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "data"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "data"


class TestMetronomeBodyFanout:
    @patch(f"{TRANSPORT}._rest_client")
    def test_contracts_are_requested_once_per_customer_with_the_id_in_the_body(self, mock_client_factory) -> None:
        client = MagicMock()
        client.paginate.side_effect = [
            # Parent customers, across two pages.
            iter([[{"id": "cust_1"}], [{"id": "cust_2"}]]),
            iter([[{"id": "contract_1", "customer_id": "cust_1"}]]),
            iter([[{"id": "contract_2", "customer_id": "cust_2"}]]),
        ]
        mock_client_factory.return_value = client

        response = metronome_source(api_key="tok", endpoint="contracts", team_id=1, job_id="job-1")
        pages = list(cast(Any, response.items()))

        assert pages == [
            [{"id": "contract_1", "customer_id": "cust_1"}],
            [{"id": "contract_2", "customer_id": "cust_2"}],
        ]
        child_calls = client.paginate.call_args_list[1:]
        assert [call.kwargs["json"] for call in child_calls] == [
            {"include_archived": True, "customer_id": "cust_1"},
            {"include_archived": True, "customer_id": "cust_2"},
        ]
        assert {call.args[0] for call in child_calls} == {"/v2/contracts/list"}

    @patch(f"{TRANSPORT}._rest_client")
    def test_customer_without_an_id_is_skipped(self, mock_client_factory) -> None:
        client = MagicMock()
        client.paginate.side_effect = [iter([[{"name": "no id here"}]])]
        mock_client_factory.return_value = client

        response = metronome_source(api_key="tok", endpoint="contracts", team_id=1, job_id="job-1")

        assert list(cast(Any, response.items())) == []
        assert client.paginate.call_count == 1


class TestMetronomeCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (
                401,
                False,
                "Metronome rejected the API token. Create a new one in Metronome under Developer > API tokens and reconnect.",
            ),
            (
                403,
                False,
                "Metronome rejected the API token. Create a new one in Metronome under Developer > API tokens and reconnect.",
            ),
            (500, False, "Metronome API returned an unexpected status code: 500"),
        ]
    )
    @patch(f"{TRANSPORT}.make_tracked_session")
    def test_status_maps_to_message(self, status_code, expected_valid, expected_message, mock_session) -> None:
        # Metronome's own auth docs say a rejected token comes back as "a 401 or 403", so both
        # codes have to land on the same message.
        mock_session.return_value.get.return_value = Mock(status_code=status_code)

        assert validate_credentials("tok") == (expected_valid, expected_message)

    @patch(f"{TRANSPORT}.make_tracked_session")
    def test_unreachable_host_is_not_reported_as_a_bad_token(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        valid, message = validate_credentials("tok")

        assert valid is False
        assert message == "Couldn't reach Metronome to validate the API token. Check your connection and try again."
