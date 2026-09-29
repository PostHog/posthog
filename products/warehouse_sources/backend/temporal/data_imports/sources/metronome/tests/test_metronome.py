import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome import (
    EPOCH_RFC_3339,
    USAGE_CUSTOMER_CONCURRENCY,
    MetronomeCursorPaginator,
    MetronomeResumeConfig,
    MetronomeWalkStart,
    _clamp_window_start,
    _fill_in_flight,
    _format_rfc3339,
    _paginator_for,
    _parallel_usage_pages,
    _usage_rows_for_customer,
    _WalkCancelled,
    get_resource,
    metronome_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.settings import (
    METRONOME_ENDPOINTS,
    USAGE_DAILY_LOOKBACK_SECONDS,
    USAGE_HOURLY_LOOKBACK_SECONDS,
    usage_history_window,
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

    @parameterized.expand([("usage",), ("usage_daily",), ("usage_hourly",)])
    def test_usage_endpoints_page_by_cursor_and_send_no_page_size(self, endpoint) -> None:
        # `POST /v1/usage` takes `next_page` in the query string but accepts no `limit`, and it
        # rejects the whole request when `limit` is present. Answering that by dropping the cursor
        # instead of the page size would import the first page and report success.
        resource = cast(
            dict[str, Any],
            get_resource(endpoint, should_use_incremental_field=False, window_starting_on=EPOCH_RFC_3339),
        )

        assert resource["endpoint"]["params"] == {}
        assert isinstance(resource["endpoint"]["paginator"], MetronomeCursorPaginator)

    @parameterized.expand([("usage",), ("usage_daily",), ("usage_hourly",)])
    def test_usage_value_is_typed_as_a_float(self, endpoint) -> None:
        # A batch of whole numbers infers an integer column, and the first fractional usage amount
        # after that no longer fits it, which fails the sync and turns the schema off.
        resource = cast(
            dict[str, Any],
            get_resource(endpoint, should_use_incremental_field=False, window_starting_on=EPOCH_RFC_3339),
        )
        data_map = resource["data_map"]

        assert isinstance(data_map({"value": 7})["value"], float)
        # No usage matched the period, which is not the same as none of it costing anything.
        assert data_map({"value": None})["value"] is None

    @parameterized.expand([("invoices",), ("contracts",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint, should_use_incremental_field=False)

    @parameterized.expand([("usage_daily", "DAY"), ("usage_hourly", "HOUR")])
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
        # An hourly table asks for whole days too; Metronome 400s on a bound off UTC midnight.
        assert body["ending_before"].endswith("T00:00:00Z")

    @parameterized.expand(
        [
            ("a_full_day_is_left_alone", "2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-03T00:00:00Z"),
            (
                "a_shorter_window_backs_the_start_off",
                "2026-09-04T00:00:00Z",
                "2026-09-04T00:00:00Z",
                "2026-09-03T00:00:00Z",
            ),
        ]
    )
    def test_clamp_window_start_holds_the_one_day_minimum(self, _name, starting_on, ending_before, expected) -> None:
        # Metronome rejects a window shorter than a day, so the end bound reaching the start has to
        # widen the request rather than send one the vendor answers with a 400.
        assert _clamp_window_start(starting_on, ending_before) == expected

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
        assert body["window_size"] == "NONE"
        assert body["starting_on"] == EPOCH_RFC_3339
        assert body["ending_before"] > EPOCH_RFC_3339
        assert body["ending_before"].endswith("T00:00:00Z")


class _FakeUsageClient:
    """Stands in for a `RESTClient`: one customer list, then one usage walk per customer."""

    def __init__(self, customer_pages, rows_by_customer, page_cursors=()) -> None:
        self.customer_pages = customer_pages
        self.rows_by_customer = rows_by_customer
        self.page_cursors = list(page_cursors)
        self.usage_bodies: list[dict[str, Any]] = []

    def paginate(self, path, **kwargs):
        if path == "/v1/customers":
            hook = kwargs.get("resume_hook")
            for index, page in enumerate(self.customer_pages):
                yield page
                # `RESTClient` offers the next page's cursor once the consumer asks for it.
                if hook is not None:
                    cursor = self.page_cursors[index] if index < len(self.page_cursors) else None
                    hook({"cursor": cursor} if cursor else None)
            return
        body = kwargs["json"]
        self.usage_bodies.append(body)
        yield self.rows_by_customer[body["customer_ids"][0]]


class _FakeClients:
    def __init__(self, client) -> None:
        self._client = client

    def get(self):
        return self._client


class TestMetronomeParallelUsage:
    def _run(self, client, walk, commit=None, endpoint="usage_daily"):
        return list(
            _parallel_usage_pages(
                cast(Any, _FakeClients(client)),
                METRONOME_ENDPOINTS[endpoint],
                {"window_size": "DAY"},
                walk,
                commit or (lambda cursor, completed: None),
            )
        )

    def test_each_customer_is_asked_for_on_its_own(self) -> None:
        # The partition is the whole point: without `customer_ids` every walk would re-read the
        # entire account, and there would be nothing independent to run in parallel.
        client = _FakeUsageClient([[{"id": "c1"}, {"id": "c2"}]], {"c1": [{"value": 1}], "c2": [{"value": 2}]})

        self._run(client, MetronomeWalkStart())

        assert [body["customer_ids"] for body in client.usage_bodies] == [["c1"], ["c2"]]
        # The pinned window rides every partitioned request, not just the first.
        assert {body["window_size"] for body in client.usage_bodies} == {"DAY"}

    def test_the_usage_amount_is_still_floated(self) -> None:
        # This path builds its own requests, so the resource's `data_map` never runs on it. Losing
        # the cast here would put an integer column back and fail the sync on the first fraction.
        client = _FakeUsageClient([[{"id": "c1"}]], {"c1": [{"value": 7}, {"value": None}]})

        batches = self._run(client, MetronomeWalkStart())

        assert isinstance(batches[0][0]["value"], float)
        assert batches[0][1]["value"] is None

    def test_a_batch_is_checkpointed_only_once_it_has_been_yielded(self) -> None:
        # The recorded set may only move over customers whose rows reached Delta. Committing while
        # a batch is still being built would let a worker rotation resume past rows never written.
        events: list[str] = []
        client = _FakeUsageClient([[{"id": "c1"}]], {"c1": [{"value": 1}]})

        for batch in _parallel_usage_pages(
            cast(Any, _FakeClients(client)),
            METRONOME_ENDPOINTS["usage_daily"],
            {"window_size": "DAY"},
            MetronomeWalkStart(),
            lambda cursor, completed: events.append(f"commit-{sorted(completed)}") if completed else None,
        ):
            events.append(f"flush-{len(batch)}")

        assert events == ["flush-1", "commit-['c1']"]

    def test_a_resumed_walk_skips_the_customers_already_written(self) -> None:
        # Re-walking a finished customer duplicates its rows on a table that appends when it
        # resumes, which is what a full refresh does.
        client = _FakeUsageClient([[{"id": "c1"}, {"id": "c2"}]], {"c1": [{"value": 1}], "c2": [{"value": 2}]})

        self._run(client, MetronomeWalkStart(completed_customers=("c1",)))

        assert [body["customer_ids"] for body in client.usage_bodies] == [["c2"]]

    def test_the_second_page_checkpoints_the_cursor_that_fetched_it(self) -> None:
        # `RESTClient.paginate` advances a deep copy of the paginator, so reading the cursor off the
        # instance here would leave it stuck and a resumed run would restart at the first page.
        client = _FakeUsageClient(
            [[{"id": "c1"}], [{"id": "c2"}]],
            {"c1": [{"value": 1}], "c2": [{"value": 2}]},
            page_cursors=["cursor-page-2"],
        )
        commits: list[tuple[Any, tuple[str, ...]]] = []

        self._run(client, MetronomeWalkStart(), commit=lambda cursor, done: commits.append((cursor, done)))

        assert commits == [(None, ("c1",)), ("cursor-page-2", ("c2",))]

    def test_only_as_many_walks_are_submitted_as_there_are_workers(self) -> None:
        # Submitting a whole page at once leaves every finished customer's rows in memory behind a
        # slow one, which is how a batch gets past the row cap.
        submitted: list[str] = []
        todo = deque(["c1", "c2", "c3", "c4", "c5", "c6"])
        in_flight: deque[Any] = deque()

        _fill_in_flight(lambda customer_id: cast(Any, submitted.append(customer_id)), todo, in_flight)

        assert len(submitted) == USAGE_CUSTOMER_CONCURRENCY
        assert len(todo) == 6 - USAGE_CUSTOMER_CONCURRENCY

    @parameterized.expand([("null", None), ("empty", "")])
    def test_a_customer_with_no_id_fails_the_walk(self, _name, bad_id) -> None:
        # `str(None)` would ask Metronome for a customer called "None", and skipping the row would
        # drop that customer's usage from the table with no signal.
        client = _FakeUsageClient([[{"id": bad_id}]], {})

        with pytest.raises(ValueError, match="no id"):
            self._run(client, MetronomeWalkStart())

    def test_a_cancelled_walk_stops_at_the_next_page(self) -> None:
        # `cancel_futures` only drops walks that never started, so one already running has to stop
        # itself, or it keeps spending the account's request budget after the consumer has gone and
        # holds the pool's threads open on the way out.
        pages_served: list[int] = []

        class _Client:
            def paginate(self, path, **kwargs):
                for index in range(5):
                    pages_served.append(index)
                    yield [{"value": index}]

        cancelled = threading.Event()
        cancelled.set()

        with pytest.raises(_WalkCancelled):
            _usage_rows_for_customer(cast(Any, _Client()), METRONOME_ENDPOINTS["usage_daily"], {}, "c1", cancelled)

        # It raises rather than returning what it had: the checkpoint records whole customers, so a
        # partial one must never be mistakable for a finished one.
        assert pages_served == [0]


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
                "an_hourly_watermark_floors_to_utc_midnight_too",
                "usage_hourly",
                datetime(2026, 3, 14, 15, 9, 26, tzinfo=UTC),
                None,
                "2026-03-14T00:00:00Z",
            ),
            (
                "a_first_sync_reaches_back_by_the_configured_depth",
                "usage_daily",
                None,
                timedelta(days=90),
                "2026-06-05T00:00:00Z",
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
                "2026-08-04T00:00:00Z",
            ),
            # The window runs to the next midnight, so the day in progress is inside it.
            (
                "a_watermark_inside_today_still_asks_for_today",
                "usage_daily",
                NOW,
                None,
                "2026-09-03T00:00:00Z",
            ),
        ]
    )
    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_bucketed_usage_window_starts_where_the_table_left_off(
        self, _name, endpoint, watermark, usage_history, expected_start, mock_parallel
    ) -> None:
        # An unaligned lower bound asks Metronome for part of a period the table already holds, and
        # the partial aggregate that comes back upserts as a second row, because the period start
        # is part of the primary key.
        with time_machine.travel(NOW, tick=False):
            metronome_source(
                api_key="tok",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                should_use_incremental_field=watermark is not None,
                db_incremental_field_last_value=watermark,
                usage_history=usage_history,
            ).items()

        body = mock_parallel.call_args.args[2]
        assert body["starting_on"] == expected_start

    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_resumed_bucketed_run_replays_the_stored_lower_bound(self, mock_parallel) -> None:
        # Resolving the bound again on a resumed attempt would move it forward, against a cursor
        # that belongs to the window the walk started with.
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = MetronomeResumeConfig(
            next_page="cursor-9", ending_before="2026-06-01T00:00:00Z", starting_on="2026-05-01T00:00:00Z"
        )

        metronome_source(
            api_key="tok", endpoint="usage_daily", team_id=1, job_id="job-1", resumable_source_manager=manager
        ).items()

        body = mock_parallel.call_args.args[2]
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
            # Stored a cutoff: replay that exact window and resume where the customer list had
            # reached, keeping the key.
            (
                "with_stored_window",
                MetronomeResumeConfig(parent_cursor="cursor-9", ending_before="2020-06-01T00:00:00Z"),
                "2020-06-01T00:00:00Z",
                "cursor-9",
                False,
            ),
            # A checkpoint written before the cutoff was stored carries none, so the walk restarts
            # with a fresh window and no seeded cursor rather than mixing two windows. The stale key
            # is cleared so the pipeline's own resume probe doesn't append onto the partial table.
            ("pre_window_checkpoint", MetronomeResumeConfig(parent_cursor="cursor-9"), None, None, True),
        ]
    )
    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_resumed_usage_run_pins_the_window(
        self,
        _name,
        resume_state,
        expected_window,
        expected_parent_cursor,
        expect_state_cleared,
        mock_parallel,
    ) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = resume_state

        metronome_source(
            api_key="tok", endpoint="usage", team_id=1, job_id="job-1", resumable_source_manager=manager
        ).items()

        body = mock_parallel.call_args.args[2]
        if expected_window is not None:
            assert body["ending_before"] == expected_window
        else:
            assert body["ending_before"] > EPOCH_RFC_3339
        assert mock_parallel.call_args.args[3].parent_cursor == expected_parent_cursor
        assert manager.clear_state.called == expect_state_cleared

    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_usage_checkpoint_saves_the_window_it_synced_with(self, mock_parallel) -> None:
        # The cutoff written into the request body and the cutoff saved for a resume must be the
        # same instant, or a retry can't replay the identical window.
        manager = MagicMock()
        manager.can_resume.return_value = False

        metronome_source(
            api_key="tok", endpoint="usage", team_id=1, job_id="job-1", resumable_source_manager=manager
        ).items()

        synced_body = mock_parallel.call_args.args[2]
        commit_checkpoint = mock_parallel.call_args.args[4]
        commit_checkpoint("cursor-3", ("c1",))

        manager.save_state.assert_called_once_with(
            MetronomeResumeConfig(
                ending_before=synced_body["ending_before"],
                starting_on=synced_body["starting_on"],
                parent_cursor="cursor-3",
                completed_customers=("c1",),
            )
        )

    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_a_finished_customer_list_checkpoints_nothing(self, mock_parallel) -> None:
        # The last page commits with no cursor and nothing outstanding. Persisting that would make
        # the next attempt resume into a walk with everything still to do.
        manager = MagicMock()
        manager.can_resume.return_value = False

        metronome_source(
            api_key="tok", endpoint="usage", team_id=1, job_id="job-1", resumable_source_manager=manager
        ).items()
        mock_parallel.call_args.args[4](None, ())

        assert manager.save_state.called is False

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

    @parameterized.expand(
        [
            ("hourly_default", "usage_hourly", None, None, 30),
            ("hourly_chosen", "usage_hourly", 7, None, 7),
            ("daily_default", "usage_daily", None, None, 365),
            ("daily_chosen_reads_as_months", "usage_daily", None, 3, 365 / 4),
            # Held to the range rather than dropped, so a depth nobody can finish cannot be typed in.
            ("above_the_range_is_held_to_it", "usage_hourly", 999, None, 30),
            ("below_the_range_is_held_to_it", "usage_daily", None, 0, 365 / 12),
            ("a_table_with_no_window", "customers", 7, 3, None),
        ]
    )
    def test_the_usage_history_window_follows_the_source_setting(
        self, _name, schema_name, hourly, daily, expected_days
    ) -> None:
        window = usage_history_window(schema_name, hourly, daily)

        assert window == (timedelta(days=expected_days) if expected_days is not None else None)

    @patch(f"{TRANSPORT}._parallel_usage_pages")
    def test_a_depth_the_user_edits_reaches_the_request(self, mock_parallel) -> None:
        # The depth is a source setting the user can change after the first sync. Reading it per run
        # is what makes an edit take effect; recording it once left the edit saved and inert.
        source = MetronomeSource()
        config = source.parse_config({"api_key": "tok", "usage_daily_history_months": 3})
        inputs = MagicMock(
            schema_name="usage_daily",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        with time_machine.travel(NOW, tick=False):
            source.source_for_pipeline(config, MagicMock(can_resume=lambda: False), inputs).items()

        assert mock_parallel.call_args.args[2]["starting_on"] == "2026-06-04T00:00:00Z"
