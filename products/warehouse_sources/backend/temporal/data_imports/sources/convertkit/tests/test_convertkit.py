import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
    _format_incremental_value,
    convertkit_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the convertkit module.
CONVERTKIT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
)


def _json_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(key: str, ids: list[int], *, has_next: bool, end_cursor: str | None) -> Response:
    return _json_response(
        {
            key: [{"id": i} for i in ids],
            "pagination": {"has_next_page": has_next, "end_cursor": end_cursor},
        }
    )


def _make_manager(resume_state: ConvertKitResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return convertkit_source(
        api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_includes_per_page_and_status_all(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(_source("subscribers", _make_manager()))

        assert params[0]["per_page"] == 1000
        # subscribers must request every status, not just active.
        assert params[0]["status"] == "all"

    @parameterized.expand(
        [
            ("created_at", "created_after", "updated_after"),
            ("updated_at", "updated_after", "created_after"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_maps_to_filter_param(
        self, incremental_field: str, expected_param: str, other_param: str, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        assert params[0][expected_param] == "2026-01-02T03:04:05Z"
        # Only the chosen field's param is set.
        assert other_param not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_when_not_using_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_on_first_sync_without_last_value(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_for_non_incremental_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("broadcasts", [1], has_next=False, end_cursor=None)])

        # broadcasts has no server-side timestamp filter and no status param.
        _rows(
            _source(
                "broadcasts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]
        assert "status" not in params[0]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_next_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("subscribers", [1, 2], has_next=True, end_cursor="C2"),
                _page("subscribers", [3], has_next=False, end_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        # The second request carries the cursor from the first page.
        assert params[1]["after"] == "C2"
        # State saved once, pointing at the first page's end_cursor; the last page ends without a save.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ConvertKitResumeConfig(after="C2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [9], has_next=False, end_cursor=None)])

        manager = _make_manager(ConvertKitResumeConfig(after="C5"))
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [9]
        manager.load_state.assert_called_once()
        assert params[0]["after"] == "C5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_end_cursor_missing_despite_has_next(self, MockSession) -> None:
        session = MockSession.return_value
        # has_next_page true but no end_cursor to advance to — must stop, not loop.
        _wire(session, [_page("subscribers", [1], has_next=True, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows_and_does_not_save(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("subscribers", [], has_next=False, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    def _response(self, status_code: int) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status_code
        return response

    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_specific_endpoint", 403, "subscribers", False),
            ("server_error", 500, None, False),
        ]
    )
    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_status_code_mapping(
        self, _name: str, status: int, endpoint: str | None, expected_valid: bool, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = self._response(status)
        is_valid, _error = validate_credentials("key", endpoint)
        assert is_valid is expected_valid

    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, error = validate_credentials("key")
        assert is_valid is False
        assert error is not None

    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_unknown_endpoint_returns_error_without_request(self, mock_session) -> None:
        is_valid, error = validate_credentials("key", "not_a_real_endpoint")
        assert is_valid is False
        assert error is not None
        mock_session.assert_not_called()


class TestConvertKitSource:
    @parameterized.expand(
        [
            ("subscribers", ["id"], "created_at"),
            ("purchases", ["id"], "transaction_time"),
            ("custom_fields", ["id"], None),
            ("email_templates", ["id"], None),
        ]
    )
    def test_source_response_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_threads_manager_and_yields(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("tags", [7], has_next=False, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("tags", manager))

        assert [r["id"] for r in rows] == [7]
        manager.can_resume.assert_called_once()


def _wire_calls(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Like ``_wire``, but snapshots the URL alongside the params of each request."""
    session.headers = {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        calls.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return calls


class TestBroadcastStats:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_the_account_wide_stats_list(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(session, [_page("broadcasts", [205, 204], has_next=False, end_cursor=None)])

        rows = _rows(_source("broadcast_stats", _make_manager()))

        assert [r["id"] for r in rows] == [205, 204]
        assert calls[0][0].endswith("/v4/broadcasts/stats")
        # Stats keep moving after a send, so no timestamp window is applied.
        assert "sent_after" not in calls[0][1]


JUNCTIONS = [
    ("form_subscribers", "forms", "/v4/forms/{}/subscribers", "form_id", "added_after"),
    ("tag_subscribers", "tags", "/v4/tags/{}/subscribers", "tag_id", "tagged_after"),
    ("sequence_subscribers", "sequences", "/v4/sequences/{}/subscribers", "sequence_id", "added_after"),
]
INCREMENTAL_JUNCTIONS = [JUNCTIONS[0], JUNCTIONS[2]]


class TestSubscriberJunctions:
    @parameterized.expand(JUNCTIONS)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_parents_and_injects_the_parent_id(
        self, endpoint: str, parent_key: str, child_path: str, parent_column: str, _filter: str, MockSession
    ) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page(parent_key, [11, 12], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
                _page("subscribers", [2], has_next=False, end_cursor=None),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager()))

        # Every row carries the parent it came from, which is what makes the key unique table-wide.
        assert [(r[parent_column], r["id"]) for r in rows] == [(11, 1), (12, 2)]
        assert calls[1][0].endswith(child_path.format(11))
        assert calls[2][0].endswith(child_path.format(12))
        # Every subscriber state, not just the active ones Kit returns by default.
        assert calls[1][1]["status"] == "all"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_form_parent_listing_includes_archived_forms(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("forms", [11], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
            ],
        )

        _rows(_source("form_subscribers", _make_manager()))

        assert calls[0][1]["status"] == "all"

    @parameterized.expand(INCREMENTAL_JUNCTIONS)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_watermark_narrows_each_child_request(
        self, endpoint: str, parent_key: str, _child_path: str, _parent_column: str, filter_param: str, MockSession
    ) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page(parent_key, [11], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
            ],
        )

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field=filter_param.replace("_after", "_at"),
            )
        )

        assert calls[1][1][filter_param] == "2026-01-02T03:04:05Z"
        # The parent listing is walked in full, so only the child is windowed.
        assert filter_param not in calls[0][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_incremental_sync_sends_the_epoch_floor(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("forms", [11], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
            ],
        )

        _rows(
            _source(
                "form_subscribers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="added_at",
            )
        )

        # The framework binds the filter param whether or not a watermark exists, so the floor
        # has to be a real timestamp rather than the string "None".
        assert calls[1][1]["added_after"] == "1970-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_window(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("tags", [11], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
            ],
        )

        _rows(
            _source(
                "tag_subscribers",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="tagged_at",
            )
        )

        assert "tagged_after" not in calls[1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_each_parent_once_its_children_are_yielded(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_calls(
            session,
            [
                _page("forms", [11, 12], has_next=False, end_cursor=None),
                _page("subscribers", [1], has_next=False, end_cursor=None),
                _page("subscribers", [2], has_next=False, end_cursor=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("form_subscribers", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[-1] == ConvertKitResumeConfig(
            completed=["/v4/forms/11/subscribers", "/v4/forms/12/subscribers"], current=None, child_state=None
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_synced_parents_and_continues_the_one_in_flight(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("forms", [11, 12], has_next=False, end_cursor=None),
                _page("subscribers", [2], has_next=False, end_cursor=None),
            ],
        )

        manager = _make_manager(
            ConvertKitResumeConfig(
                completed=["/v4/forms/11/subscribers"],
                current="/v4/forms/12/subscribers",
                child_state={"after": "C9"},
            )
        )
        rows = _rows(_source("form_subscribers", manager))

        assert [r["form_id"] for r in rows] == [12]
        assert [url for url, _ in calls] == [
            "https://api.kit.com/v4/forms",
            "https://api.kit.com/v4/forms/12/subscribers",
        ]
        assert calls[1][1]["after"] == "C9"


class TestValidateFanoutCredentials:
    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_probes_the_parent_listing(self, mock_session) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        is_valid, _error = validate_credentials("key", "form_subscribers")

        assert is_valid is True
        # The child path carries an unresolved id placeholder, so probing it would 404 and
        # report a working key as broken.
        assert mock_session.return_value.get.call_args.args[0] == "https://api.kit.com/v4/forms?per_page=1"


class TestGrowthStats:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_the_single_stats_object_without_paging(self, MockSession) -> None:
        session = MockSession.return_value
        stats = {
            "cancellations": 1,
            "net_new_subscribers": 2,
            "new_subscribers": 3,
            "subscribers": 40,
            "starting": "2026-02-10T00:00:00-05:00",
            "ending": "2026-02-24T23:59:59-05:00",
        }
        calls = _wire_calls(session, [_json_response({"stats": stats})])

        rows = _rows(_source("growth_stats", _make_manager()))

        # One row out of an object body, and the run stops on a response carrying no
        # pagination envelope — a second request would exhaust the wired responses.
        assert rows == [stats]
        assert calls[0][0].endswith("/v4/account/growth_stats")
        assert "per_page" not in calls[0][1]


class TestSequenceEmails:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_sequences_and_keys_rows_by_sequence(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("sequences", [11, 12], has_next=False, end_cursor=None),
                _page("emails", [1], has_next=False, end_cursor=None),
                _page("emails", [2], has_next=False, end_cursor=None),
            ],
        )

        rows = _rows(_source("sequence_emails", _make_manager()))

        assert [(r["sequence_id"], r["id"]) for r in rows] == [(11, 1), (12, 2)]
        assert calls[1][0].endswith("/v4/sequences/11/emails")
        assert calls[2][0].endswith("/v4/sequences/12/emails")


def _clicks_page(broadcast_id: int, link_ids: list[int]) -> Response:
    return _json_response(
        {
            "broadcast": {
                "id": broadcast_id,
                "clicks": [{"id": i, "url": f"https://example.com/{i}", "unique_clicks": i} for i in link_ids],
            },
            "pagination": {"has_next_page": False, "end_cursor": None},
        }
    )


class TestBroadcastClicks:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_the_nested_click_list_and_injects_the_broadcast_id(self, MockSession) -> None:
        session = MockSession.return_value
        calls = _wire_calls(
            session,
            [
                _page("broadcasts", [11, 12], has_next=False, end_cursor=None),
                _clicks_page(11, [51, 52]),
                _clicks_page(12, [53]),
            ],
        )

        rows = _rows(_source("broadcast_clicks", _make_manager()))

        assert [(r["broadcast_id"], r["id"]) for r in rows] == [(11, 51), (11, 52), (12, 53)]
        assert rows[0]["url"] == "https://example.com/51"
        assert calls[1][0].endswith("/v4/broadcasts/11/clicks")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_broadcast_with_no_click_record_does_not_fail_the_fan_out(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_calls(
            session,
            [
                _page("broadcasts", [11, 12], has_next=False, end_cursor=None),
                _json_response({"errors": ["Not Found"]}, status_code=404),
                _clicks_page(12, [53]),
            ],
        )

        rows = _rows(_source("broadcast_clicks", _make_manager()))

        assert [(r["broadcast_id"], r["id"]) for r in rows] == [(12, 53)]
