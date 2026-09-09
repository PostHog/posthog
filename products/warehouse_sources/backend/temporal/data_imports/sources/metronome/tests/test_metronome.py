from datetime import UTC, datetime
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome import (
    EPOCH_RFC_3339,
    MetronomeCursorPaginator,
    MetronomeResumeConfig,
    _format_rfc3339,
    _paginator_for,
    get_resource,
    metronome_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.settings import (
    METRONOME_ENDPOINTS,
    USAGE_DAILY_LOOKBACK_SECONDS,
    USAGE_HOURLY_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.source import MetronomeSource

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome"

# The instant every resolved window in these tests is measured against.
NOW = datetime(2026, 9, 3, 12, 34, 56, tzinfo=UTC)


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

    @parameterized.expand([("customers",), ("products",), ("packages",), ("billable_metrics",), ("plans",), ("usage",)])
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

    @parameterized.expand([("usage_daily", "day"), ("usage_hourly", "hour")])
    def test_bucketed_usage_merges_on_a_body_window_with_no_injected_param(self, endpoint, window_size) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(endpoint, should_use_incremental_field=True, window_starting_on="2026-01-01T00:00:00Z"),
        )

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        # The window rides the body, which the framework's incremental config cannot reach.
        assert "incremental" not in resource["endpoint"]
        body = resource["endpoint"]["json"]
        assert body["window_size"] == window_size
        assert body["starting_on"] == "2026-01-01T00:00:00Z"
        assert body["ending_before"] > "2026-01-01T00:00:00Z"

    @parameterized.expand([("usage_daily",), ("usage_hourly",)])
    def test_get_resource_rejects_a_bucketed_endpoint_with_no_lower_bound(self, endpoint) -> None:
        with pytest.raises(ValueError, match="needs a resolved"):
            get_resource(endpoint, should_use_incremental_field=True)

    def test_usage_resource_sends_the_full_window_in_the_body(self) -> None:
        # `POST /v1/usage` rejects the request unless the body carries `window_size`, `starting_on`
        # and `ending_before`. `ending_before` is the sync time, so it can't be a static default.
        resource = cast(dict[str, Any], get_resource("usage", should_use_incremental_field=False))

        assert resource["endpoint"]["method"] == "post"
        body = resource["endpoint"]["json"]
        assert body["window_size"] == "none"
        assert body["starting_on"] == EPOCH_RFC_3339
        assert body["ending_before"] > EPOCH_RFC_3339


class TestMetronomeSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "created_at", "asc"),
            ("audit_logs", ["id"], "timestamp", "asc"),
            ("pricing_units", ["id"], None, "asc"),
            ("plans", ["id"], None, "asc"),
            ("usage", ["customer_id", "billable_metric_id"], None, "asc"),
            # Bucketed usage arrives grouped by customer rather than by period, so its watermark
            # may only commit once the whole walk has finished.
            ("usage_daily", ["customer_id", "billable_metric_id", "start_timestamp"], "start_timestamp", "desc"),
            ("usage_hourly", ["customer_id", "billable_metric_id", "start_timestamp"], "start_timestamp", "desc"),
        ]
    )
    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_top_level_response_shape(self, endpoint, primary_keys, partition_key, sort_mode, _mock) -> None:
        response = metronome_source(api_key="tok", endpoint=endpoint, team_id=1, job_id="job-1")

        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.sort_mode == sort_mode
        # Each of these tables walks the resume path, whose checkpoint advances per page, so the
        # batcher must flush one page at a time or a resumed sync appends past unflushed pages.
        assert response.chunk_size == 1

    @parameterized.expand(
        [
            (
                "a_watermark_is_floored_to_the_day",
                "usage_daily",
                datetime(2026, 3, 14, 15, 9, 26, tzinfo=UTC),
                None,
                "2026-03-14T00:00:00Z",
            ),
            (
                "a_watermark_is_floored_to_the_hour",
                "usage_hourly",
                datetime(2026, 3, 14, 15, 9, 26, tzinfo=UTC),
                None,
                "2026-03-14T15:00:00Z",
            ),
            (
                "a_first_sync_starts_where_the_schema_recorded_its_range",
                "usage_daily",
                None,
                datetime(2025, 12, 1, 6, 30, tzinfo=UTC),
                "2025-12-01T00:00:00Z",
            ),
            (
                "an_unrecorded_first_sync_falls_back_to_the_daily_bound",
                "usage_daily",
                None,
                None,
                "2025-09-03T00:00:00Z",
            ),
            (
                "an_unrecorded_first_sync_falls_back_to_the_hourly_bound",
                "usage_hourly",
                None,
                None,
                "2026-08-04T12:00:00Z",
            ),
        ]
    )
    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_bucketed_usage_window_starts_where_the_table_left_off(
        self, _name, endpoint, watermark, history_start, expected_start, mock_rest_api_resource
    ) -> None:
        # An unaligned lower bound asks Metronome for part of a period the table already holds, and
        # the partial aggregate that comes back upserts as a second row, because the period start
        # is part of the primary key.
        with freeze_time(NOW):
            metronome_source(
                api_key="tok",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                should_use_incremental_field=watermark is not None,
                db_incremental_field_last_value=watermark,
                history_start=history_start,
            )

        body = mock_rest_api_resource.call_args.args[0]["resources"][0]["endpoint"]["json"]
        assert body["starting_on"] == expected_start

    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_resumed_bucketed_run_replays_the_stored_lower_bound(self, mock_rest_api_resource) -> None:
        # Resolving the bound again on a resumed attempt would move it forward, against a cursor
        # that belongs to the window the walk started with.
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = MetronomeResumeConfig(
            next_page="cursor-9", ending_before="2026-06-01T00:00:00Z", starting_on="2026-05-01T00:00:00Z"
        )

        metronome_source(
            api_key="tok", endpoint="usage_daily", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        body = mock_rest_api_resource.call_args.args[0]["resources"][0]["endpoint"]["json"]
        assert body["starting_on"] == "2026-05-01T00:00:00Z"
        assert body["ending_before"] == "2026-06-01T00:00:00Z"

    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_resume_state_seeds_the_paginator_cursor(self, mock_rest_api_resource) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = MetronomeResumeConfig(next_page="cursor-9")

        metronome_source(
            api_key="tok", endpoint="customers", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "cursor-9"}

    @parameterized.expand(
        [
            # Stored a cutoff: replay that exact window and resume from its cursor, keeping the key.
            (
                "with_stored_window",
                MetronomeResumeConfig(next_page="cursor-9", ending_before="2020-06-01T00:00:00Z"),
                "2020-06-01T00:00:00Z",
                {"cursor": "cursor-9"},
                False,
            ),
            # A checkpoint written before the cutoff was stored carries none, so the walk restarts
            # with a fresh window and no seeded cursor rather than mixing two windows. The stale key
            # is cleared so the pipeline's own resume probe doesn't append onto the partial table.
            ("pre_window_checkpoint", MetronomeResumeConfig(next_page="cursor-9"), None, None, True),
        ]
    )
    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_resumed_usage_run_pins_the_window(
        self,
        _name,
        resume_state,
        expected_window,
        expected_paginator_state,
        expect_state_cleared,
        mock_rest_api_resource,
    ) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = resume_state

        metronome_source(api_key="tok", endpoint="usage", team_id=1, job_id="job-1", resumable_source_manager=manager)

        body = mock_rest_api_resource.call_args.args[0]["resources"][0]["endpoint"]["json"]
        if expected_window is not None:
            assert body["ending_before"] == expected_window
        else:
            assert body["ending_before"] > EPOCH_RFC_3339
        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == expected_paginator_state
        assert manager.clear_state.called == expect_state_cleared

    @patch(f"{TRANSPORT}.rest_api_resource")
    def test_usage_checkpoint_saves_the_window_it_synced_with(self, mock_rest_api_resource) -> None:
        # The cutoff written into the request body and the cutoff saved for a resume must be the
        # same instant, or a retry can't replay the identical window.
        manager = MagicMock()
        manager.can_resume.return_value = False

        metronome_source(api_key="tok", endpoint="usage", team_id=1, job_id="job-1", resumable_source_manager=manager)

        synced_body = mock_rest_api_resource.call_args.args[0]["resources"][0]["endpoint"]["json"]
        save_checkpoint = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        save_checkpoint({"cursor": "cursor-3"})

        manager.save_state.assert_called_once_with(
            MetronomeResumeConfig(
                next_page="cursor-3",
                ending_before=synced_body["ending_before"],
                starting_on=synced_body["starting_on"],
            )
        )

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
        # Fan-out tables don't resume, so they keep the default chunk size — a per-page flush here
        # would cost a Delta commit per page on the largest tables for no durability gain.
        assert response.chunk_size is None
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


class TestMetronomeSchemas:
    def _schema(self, name: str):
        source = MetronomeSource()
        config = source.parse_config({"api_key": "tok"})
        return {schema.name: schema for schema in source.get_schemas(config, team_id=1)}[name]

    @parameterized.expand(
        [
            ("usage_daily", USAGE_DAILY_LOOKBACK_SECONDS),
            ("usage_hourly", USAGE_HOURLY_LOOKBACK_SECONDS),
        ]
    )
    def test_bucketed_usage_merges_incrementally_and_starts_off(self, name, lookback_seconds) -> None:
        schema = self._schema(name)

        assert schema.supports_incremental is True
        # Appending would duplicate every period the lookback re-reads.
        assert schema.supports_append is False
        assert [field["field"] for field in schema.incremental_fields] == ["start_timestamp"]
        assert schema.should_sync_default is False
        assert schema.default_incremental_lookback_seconds == lookback_seconds

    def test_the_lifetime_usage_table_keeps_its_defaults(self) -> None:
        schema = self._schema("usage")

        assert schema.supports_incremental is False
        assert schema.should_sync_default is True
        assert schema.default_incremental_lookback_seconds is None
