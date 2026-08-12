import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    INVALID_START_DATE_ERROR,
    START_DATE_TOO_OLD_ERROR,
    LoopReturnsPaginator,
    LoopReturnsResumeConfig,
    endpoint_permissions,
    loop_returns_source,
    next_cursor,
    probe_endpoint,
    resolve_filter_field,
    resolve_window_start,
    start_date_error,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    DEFAULT_BACKFILL_DAYS,
    LOOP_RETURNS_ENDPOINTS,
    MAX_BACKFILL_DAYS,
    MAX_WINDOW_DAYS,
    RETURN_STATES,
)

WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
API_KEY = "loop_test_key"
API_VERSION = "v1"


class FakeResumableSourceManager(ResumableSourceManager[LoopReturnsResumeConfig]):
    def __init__(self, state: Optional[LoopReturnsResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[LoopReturnsResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[LoopReturnsResumeConfig]:
        return self.state

    def save_state(self, data: LoopReturnsResumeConfig) -> None:
        self.saved.append(data)


def _http_response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _paginator(endpoint: str = "returns", *, days: int = 250) -> LoopReturnsPaginator:
    return LoopReturnsPaginator(
        config=LOOP_RETURNS_ENDPOINTS[endpoint],
        window_start=WINDOW_START,
        window_end=WINDOW_START + timedelta(days=days),
        filter_field="created_at",
    )


def _request() -> Request:
    return Request(method="GET", url="https://api.loopreturns.com/api/v1/warehouse/return/list")


def _walk(paginator: LoopReturnsPaginator, responses: list[Any], max_pages: int = 40) -> list[dict[str, Any]]:
    """Drive the paginator through `responses` and return the params of each request it built."""
    request = _request()
    paginator.init_request(request)
    sent = [dict(request.params or {})]

    for body in responses:
        if len(sent) >= max_pages:
            break
        paginator.update_state(_http_response(body))
        paginator.update_request(request)
        if not paginator.has_next_page:
            break
        sent.append(dict(request.params or {}))

    return sent


class TestLoopReturnsPaginator:
    def test_first_request_carries_the_window_state_and_pagination_params(self) -> None:
        request = _request()
        _paginator().init_request(request)

        assert request.params == {
            "from": "2024-01-01T00:00:00.000Z",
            "to": "2024-04-30T00:00:00.000Z",
            "filter": "created_at",
            "state": "open",
            "paginate": "true",
            "pageSize": 250,
        }

    def test_windows_never_exceed_the_api_range_cap(self) -> None:
        # Loop rejects a range wider than 120 days, so every window has to stay inside it.
        sent = _walk(_paginator(days=250), [{"returns": [], "nextPageUrl": None}] * 3)

        for params in sent:
            start = datetime.fromisoformat(params["from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(params["to"].replace("Z", "+00:00"))
            assert end - start <= timedelta(days=MAX_WINDOW_DAYS)

    def test_windows_walk_the_whole_range_then_restart_for_the_next_state(self) -> None:
        # Loop's `state` filter takes one value and defaults to open/closed/expired, so cancelled
        # and in-review returns only land if each state gets its own pass over the full range.
        sent = _walk(_paginator(days=250), [{"returns": [], "nextPageUrl": None}] * 20)

        first_pass = [(params["from"], params["to"]) for params in sent[:3]]
        assert first_pass == [
            ("2024-01-01T00:00:00.000Z", "2024-04-30T00:00:00.000Z"),
            ("2024-04-30T00:00:00.000Z", "2024-08-28T00:00:00.000Z"),
            ("2024-08-28T00:00:00.000Z", "2024-09-07T00:00:00.000Z"),
        ]
        assert [params["state"] for params in sent] == [state for state in RETURN_STATES for _ in range(3)]
        assert sent[3]["from"] == "2024-01-01T00:00:00.000Z"

    def test_cursor_pages_stay_inside_the_current_window(self) -> None:
        # A next page that dropped `from`/`to` would walk back through all of history on every page.
        sent = _walk(
            _paginator(days=10),
            [
                {"returns": [], "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc"},
                {"returns": [], "nextPageUrl": None},
            ],
        )

        assert [params.get("cursor") for params in sent[:2]] == [None, "abc"]
        assert sent[1]["from"] == sent[0]["from"]
        assert sent[1]["to"] == sent[0]["to"]

    @pytest.mark.parametrize(
        ("label", "second_body"),
        [
            ("next_link_without_a_cursor", {"returns": [], "nextPageUrl": "https://api.loopreturns.com/next"}),
            (
                "repeated_cursor",
                {"returns": [], "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc"},
            ),
        ],
    )
    def test_pagination_that_cannot_advance_moves_on_instead_of_looping(self, label: str, second_body: Any) -> None:
        first_body = {
            "returns": [],
            "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc",
        }
        sent = _walk(_paginator(days=10), [first_body, second_body, {"returns": [], "nextPageUrl": None}])

        # Page three is the next state's pass over the same window, not a third fetch of the cursor.
        assert [params["state"] for params in sent[:3]] == ["open", "open", "closed"]
        assert sent[2].get("cursor") is None

    def test_resume_state_round_trips_the_window_state_and_cursor(self) -> None:
        paginator = _paginator(days=250)
        _walk(
            paginator,
            [
                {"returns": [], "nextPageUrl": None},
                {"returns": [], "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=xyz"},
            ],
        )
        saved = paginator.get_resume_state()
        assert saved == {"window_start": "2024-04-30T00:00:00.000Z", "state_index": 0, "cursor": "xyz"}

        resumed = _paginator(days=250)
        resumed.set_resume_state(cast(dict[str, Any], saved))
        request = _request()
        resumed.init_request(request)

        assert request.params is not None
        assert request.params["from"] == "2024-04-30T00:00:00.000Z"
        assert request.params["cursor"] == "xyz"
        assert request.params["state"] == "open"

    def test_resume_state_restores_a_later_state_pass(self) -> None:
        resumed = _paginator(days=10)
        resumed.set_resume_state({"window_start": "2024-01-05T00:00:00.000Z", "state_index": 3, "cursor": None})
        request = _request()
        resumed.init_request(request)

        assert request.params is not None
        assert request.params["state"] == RETURN_STATES[3]
        assert "cursor" not in request.params

    @pytest.mark.parametrize(
        ("label", "state"),
        [
            ("missing_window_start", {}),
            ("null_window_start", {"window_start": None}),
        ],
    )
    def test_unusable_resume_state_is_ignored(self, label: str, state: dict[str, Any]) -> None:
        paginator = _paginator(days=10)
        paginator.set_resume_state(state)
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["from"] == "2024-01-01T00:00:00.000Z"

    def test_a_watermark_after_the_window_end_never_inverts_the_range(self) -> None:
        # A watermark at (or past) "now" must not produce `to` before `from`, which Loop rejects.
        paginator = LoopReturnsPaginator(
            config=LOOP_RETURNS_ENDPOINTS["returns"],
            window_start=WINDOW_START,
            window_end=WINDOW_START - timedelta(days=1),
            filter_field="created_at",
        )
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["to"] == request.params["from"]

    def test_endpoint_without_pagination_or_states_only_windows(self) -> None:
        sent = _walk(_paginator("advanced_shipping_notices", days=200), [[], []])

        assert [(params["from"], params["to"]) for params in sent] == [
            ("2024-01-01T00:00:00.000Z", "2024-04-30T00:00:00.000Z"),
            ("2024-04-30T00:00:00.000Z", "2024-07-19T00:00:00.000Z"),
        ]
        assert all("state" not in params and "cursor" not in params for params in sent)
        # The ASN report doesn't accept the `filter` param, so it must not be sent.
        assert all("filter" not in params for params in sent)


class TestNextCursor:
    @pytest.mark.parametrize(
        ("label", "body", "expected"),
        [
            ("cursor_in_next_link", {"nextPageUrl": "https://api.loopreturns.com/x?cursor=c1&pageSize=250"}, "c1"),
            ("last_page", {"nextPageUrl": None}, None),
            ("no_next_link", {"returns": []}, None),
            ("next_link_without_cursor", {"nextPageUrl": "https://api.loopreturns.com/x?pageSize=250"}, None),
            ("bare_array_body", [{"id": "1"}], None),
        ],
    )
    def test_next_cursor(self, label: str, body: Any, expected: Optional[str]) -> None:
        assert next_cursor(_http_response(body)) == expected

    def test_non_json_body_has_no_cursor(self) -> None:
        response = Response()
        response.status_code = 200
        response._content = b"<html>error</html>"

        assert next_cursor(response) is None


class TestResolveWindowStart:
    @pytest.mark.parametrize(
        ("label", "kwargs", "expected"),
        [
            (
                "incremental_run_resumes_at_the_watermark",
                {"should_use_incremental_field": True, "db_incremental_field_last_value": "2025-03-04T05:06:07Z"},
                datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC),
            ),
            (
                "incremental_run_without_a_watermark_uses_the_start_date",
                {"should_use_incremental_field": True, "start_date": "2023-02-01"},
                datetime(2023, 2, 1, tzinfo=UTC),
            ),
            ("full_refresh_uses_the_start_date", {"start_date": "2023-02-01"}, datetime(2023, 2, 1, tzinfo=UTC)),
            (
                "full_refresh_ignores_the_watermark",
                {"db_incremental_field_last_value": "2025-03-04T05:06:07Z", "start_date": "2023-02-01"},
                datetime(2023, 2, 1, tzinfo=UTC),
            ),
            ("no_start_date_backfills_the_default_window", {}, WINDOW_START - timedelta(days=DEFAULT_BACKFILL_DAYS)),
            (
                "blank_start_date_backfills_the_default_window",
                {"start_date": ""},
                WINDOW_START - timedelta(days=DEFAULT_BACKFILL_DAYS),
            ),
        ],
    )
    def test_resolve_window_start(self, label: str, kwargs: dict[str, Any], expected: datetime) -> None:
        # Loop only returns the previous 24 hours when `from`/`to` are omitted, so a wrong start
        # here silently reduces a backfill to one day.
        assert resolve_window_start(now=WINDOW_START, **kwargs) == expected

    def test_a_naive_watermark_is_treated_as_utc(self) -> None:
        assert resolve_window_start(
            now=WINDOW_START,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 3, 4, 5, 6, 7),
        ) == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)


class TestStartDateError:
    @pytest.mark.parametrize(
        ("label", "start_date", "expected"),
        [
            ("unparseable", "not-a-date", INVALID_START_DATE_ERROR),
            ("impossible_calendar_date", "2024-13-01", INVALID_START_DATE_ERROR),
            ("reaches_back_past_the_cap", "1000-01-01", START_DATE_TOO_OLD_ERROR),
            ("within_the_cap", "2023-06-01", None),
        ],
    )
    def test_start_date_error(self, label: str, start_date: str, expected: Optional[str]) -> None:
        # A start date the paginator can't cheaply walk (unparseable, or older than MAX_BACKFILL_DAYS)
        # must be caught here, before a backfill fans out into thousands of empty-window requests.
        now = datetime(2025, 8, 4, tzinfo=UTC)
        assert start_date_error(start_date, now=now) == expected

    def test_the_cap_floor_is_measured_from_now(self) -> None:
        now = datetime(2025, 8, 4, tzinfo=UTC)
        floor = now - timedelta(days=MAX_BACKFILL_DAYS)
        assert start_date_error(floor.isoformat(), now=now) is None
        assert start_date_error((floor - timedelta(days=1)).isoformat(), now=now) == START_DATE_TOO_OLD_ERROR


class TestResolveFilterField:
    @pytest.mark.parametrize(
        ("label", "should_use_incremental_field", "incremental_field", "expected"),
        [
            ("honors_the_chosen_cursor", True, "updated_at", "updated_at"),
            ("honors_created_at", True, "created_at", "created_at"),
            ("unknown_field_falls_back", True, "closed_at", "created_at"),
            ("no_field_falls_back", True, None, "created_at"),
            ("full_refresh_windows_on_created_at", False, "updated_at", "created_at"),
        ],
    )
    def test_resolve_filter_field(
        self, label: str, should_use_incremental_field: bool, incremental_field: Optional[str], expected: str
    ) -> None:
        assert resolve_filter_field(should_use_incremental_field, incremental_field) == expected


class TestLoopReturnsSource:
    def _drive(
        self,
        endpoint: str,
        responses: list[Response],
        manager: Optional[FakeResumableSourceManager] = None,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], list[Any], FakeResumableSourceManager]:
        manager = manager or FakeResumableSourceManager()
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = loop_returns_source(
                api_key=API_KEY,
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                api_version=API_VERSION,
                resumable_source_manager=manager,
                now=WINDOW_START,
                **kwargs,
            )
            rows = [row for batch in cast(Iterable[Any], source_response.items()) for row in batch]

        return sent_params, rows, manager

    @pytest.mark.parametrize(
        ("endpoint", "body", "expected_ids"),
        [
            ("returns", {"returns": [{"id": "r1"}, {"id": "r2"}], "nextPageUrl": None}, ["r1", "r2"]),
            ("advanced_shipping_notices", [{"id": 1}, {"id": 2}], [1, 2]),
            ("destinations", {"destinations": [{"id": 7}]}, [7]),
        ],
    )
    def test_rows_are_extracted_from_each_endpoints_response_shape(
        self, endpoint: str, body: Any, expected_ids: list[Any]
    ) -> None:
        states = len(LOOP_RETURNS_ENDPOINTS[endpoint].states) or 1
        _, rows, _ = self._drive(
            endpoint, [_http_response(body) for _ in range(states)], start_date="2023-12-31T00:00:00Z"
        )

        assert [row["id"] for row in rows] == expected_ids * states

    @pytest.mark.parametrize("api_version", ["v1", "2026-07"])
    def test_the_pinned_version_is_the_url_path_segment(self, api_version: str) -> None:
        # Loop carries the version in the URL path, so the resolved pin must land in every request:
        # a v1-pinned source keeps hitting `/api/v1` and a 2026-07 source hits `/api/2026-07`.
        sent_urls: list[str] = []

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            return _http_response({"destinations": []})

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = loop_returns_source(
                api_key=API_KEY,
                endpoint="destinations",
                team_id=1,
                job_id="job-1",
                api_version=api_version,
                resumable_source_manager=FakeResumableSourceManager(),
                now=WINDOW_START,
            )
            list(cast(Iterable[Any], source_response.items()))

        assert sent_urls
        assert all(url.startswith(f"https://api.loopreturns.com/api/{api_version}/") for url in sent_urls)

    def test_a_returns_sync_covers_every_state(self) -> None:
        sent_params, _, _ = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in RETURN_STATES],
            start_date="2023-12-31T00:00:00Z",
        )

        assert [params["state"] for params in sent_params] == list(RETURN_STATES)

    def test_an_incremental_run_starts_at_the_watermark_and_windows_on_the_chosen_field(self) -> None:
        sent_params, _, _ = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in RETURN_STATES],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-12-25T00:00:00Z",
            incremental_field="updated_at",
        )

        assert sent_params[0]["from"] == "2023-12-25T00:00:00.000Z"
        assert sent_params[0]["filter"] == "updated_at"

    def test_state_is_checkpointed_after_each_batch(self) -> None:
        _, _, manager = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in RETURN_STATES],
            start_date="2023-12-31T00:00:00Z",
        )

        assert manager.saved == [
            LoopReturnsResumeConfig(window_start="2023-12-31T00:00:00.000Z", state_index=index, cursor=None)
            for index in range(1, len(RETURN_STATES))
        ]

    def test_a_resumed_run_picks_up_at_the_saved_state_pass(self) -> None:
        manager = FakeResumableSourceManager(
            LoopReturnsResumeConfig(window_start="2023-12-31T12:00:00.000Z", state_index=3, cursor="c9")
        )
        sent_params, _, _ = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in range(2)],
            manager=manager,
            start_date="2023-12-31T00:00:00Z",
        )

        assert sent_params[0]["state"] == RETURN_STATES[3]
        assert sent_params[0]["cursor"] == "c9"
        assert sent_params[0]["from"] == "2023-12-31T12:00:00.000Z"
        # The next pass restarts at the configured start date, not the resumed window.
        assert sent_params[1]["from"] == "2023-12-31T00:00:00.000Z"

    def test_destinations_are_not_resumed_or_windowed(self) -> None:
        manager = FakeResumableSourceManager(
            LoopReturnsResumeConfig(window_start="2023-12-31T00:00:00.000Z", state_index=2, cursor="c9")
        )
        sent_params, _, _ = self._drive("destinations", [_http_response({"destinations": []})], manager=manager)

        assert sent_params == [{}]
        assert manager.saved == []

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_partition_keys"),
        [
            ("returns", ["id"], ["created_at"]),
            ("advanced_shipping_notices", ["id", "return_line_item_id"], ["created_at"]),
            ("destinations", ["id"], None),
        ],
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, expected_primary_keys: list[str], expected_partition_keys: Optional[list[str]]
    ) -> None:
        # An ASN key of just `id` would seed duplicates if `id` repeats per return, and every later
        # merge would multi-match them.
        source_response = loop_returns_source(
            api_key=API_KEY,
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            api_version=API_VERSION,
            resumable_source_manager=FakeResumableSourceManager(),
        )

        assert source_response.primary_keys == expected_primary_keys
        assert source_response.partition_keys == expected_partition_keys

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expected_sort_mode"),
        [(True, "desc"), (False, "asc")],
    )
    def test_incremental_syncs_defer_the_watermark_write(
        self, should_use_incremental_field: bool, expected_sort_mode: str
    ) -> None:
        # Loop documents no ordering within a window, so an "asc" claim would checkpoint a
        # watermark past rows a crashed run never fetched.
        source_response = loop_returns_source(
            api_key=API_KEY,
            endpoint="returns",
            team_id=1,
            job_id="job-1",
            api_version=API_VERSION,
            resumable_source_manager=FakeResumableSourceManager(),
            should_use_incremental_field=should_use_incremental_field,
        )

        assert source_response.sort_mode == expected_sort_mode


class TestCredentialValidation:
    def _session(self, responses: list[Response]) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = responses
        return session

    @pytest.mark.parametrize(
        ("label", "status_codes", "expected_valid"),
        [
            ("returns_readable", [200], True),
            # A key scoped only for destinations still works, just for fewer tables.
            ("returns_denied_destinations_readable", [401, 200], True),
            ("everything_denied", [401, 401], False),
            ("forbidden", [403, 403], False),
            ("server_error", [500, 500], False),
        ],
    )
    def test_validate_credentials(self, label: str, status_codes: list[int], expected_valid: bool) -> None:
        responses = [_http_response({}, status_code=code) for code in status_codes]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session(responses),
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    def test_a_denied_key_names_the_scope_to_add(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session([_http_response({}, status_code=401) for _ in range(2)]),
        ):
            _, error = validate_credentials(API_KEY, API_VERSION)

        assert error is not None
        assert "Returns" in error

    def test_validating_one_schema_probes_only_that_endpoint(self) -> None:
        session = self._session([_http_response({"destinations": []})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION, schema_name="destinations")

        assert (is_valid, error) == (True, None)
        assert session.get.call_args.args[0] == "https://api.loopreturns.com/api/v1/destinations"

    @pytest.mark.parametrize("api_version", ["v1", "2026-07"])
    def test_probe_uses_the_pinned_version_in_the_url(self, api_version: str) -> None:
        session = self._session([_http_response({"returns": [], "nextPageUrl": None})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            probe_endpoint(API_KEY, api_version, "returns")

        assert session.get.call_args.args[0] == f"https://api.loopreturns.com/api/{api_version}/warehouse/return/list"

    def test_a_network_failure_is_reported_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = RequestsConnectionError("no route to host")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is False
        assert error is not None and "no route to host" in error

    def test_probe_sends_the_api_key_in_loops_auth_header(self) -> None:
        session = self._session([_http_response({"returns": [], "nextPageUrl": None})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            probe_endpoint(API_KEY, API_VERSION, "returns")

        assert session.get.call_args.kwargs["headers"] == {"X-Authorization": API_KEY}

    def test_endpoint_permissions_reports_each_table_separately(self) -> None:
        responses = [_http_response({}, status_code=200), _http_response({}, status_code=401)]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session(responses),
        ):
            permissions = endpoint_permissions(API_KEY, API_VERSION, ["returns", "destinations"])

        assert permissions["returns"] is None
        assert permissions["destinations"] is not None
        assert "Destinations (Read)" in cast(str, permissions["destinations"])
