import json
from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly import (
    ROOTLY_BASE_URL,
    ROOTLY_JSON_API_MEDIA_TYPE,
    RootlyResumeConfig,
    _build_url,
    _clamp_future_value_to_now,
    _flatten_item,
    _format_incremental_value,
    probe_credentials,
    rootly_source,
)

# The REST client builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# probe_credentials builds its own tracked session in the rootly module.
ROOTLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"links": {"next": next_url}}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: RootlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's url/params AT SEND TIME.

    ``request.params`` is mutated in place across pages and the next-URL paginator rewrites
    ``request.url``, so inspecting the request after the run shows only the final state —
    snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str = "incidents", manager: mock.MagicMock | None = None, **kwargs: Any):
    return rootly_source(
        api_key="rootly_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://api.rootly.com/v1/users", {}) == "https://api.rootly.com/v1/users"

    def test_bracket_params_are_percent_encoded(self) -> None:
        # Rootly is Rails/JSON:API and parses percent-encoded brackets; urlencode keeps them safe.
        url = _build_url("https://api.rootly.com/v1/incidents", {"page[size]": 100})
        assert url == "https://api.rootly.com/v1/incidents?page%5Bsize%5D=100"


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor-token", "cursor-token"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor-token") == "cursor-token"


class TestFlattenItem:
    def test_attributes_hoisted_to_root_and_id_type_kept(self) -> None:
        item = {
            "id": "123",
            "type": "incidents",
            "attributes": {"title": "DB down", "status": "started", "created_at": "2026-01-01T00:00:00Z"},
        }
        assert _flatten_item(item) == {
            "id": "123",
            "type": "incidents",
            "title": "DB down",
            "status": "started",
            "created_at": "2026-01-01T00:00:00Z",
        }

    def test_missing_attributes_is_safe(self) -> None:
        assert _flatten_item({"id": "123", "type": "incidents"}) == {"id": "123", "type": "incidents"}


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_links_next_and_flattens(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"
        snapshots = _wire(
            session,
            [
                _response([{"id": "1", "type": "incidents", "attributes": {"title": "A"}}], next_url=second),
                _response([{"id": "2", "type": "incidents", "attributes": {"title": "B"}}]),
            ],
        )

        rows = _rows(_source())

        assert rows == [
            {"id": "1", "type": "incidents", "title": "A"},
            {"id": "2", "type": "incidents", "title": "B"},
        ]
        assert snapshots[0]["url"] == f"{ROOTLY_BASE_URL}/incidents"
        assert snapshots[0]["params"] == {"page[size]": 100}
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == second
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_except_the_last(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"
        _wire(
            session,
            [
                _response([{"id": "1", "attributes": {}}], next_url=second),
                _response([{"id": "2", "attributes": {}}]),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager=manager))

        # State saved once (pointing at the second page) so a crash re-yields that page; nothing
        # is saved after the final page (no next link).
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RootlyResumeConfig(next_url=second)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=3"
        snapshots = _wire(session, [_response([{"id": "9", "attributes": {"title": "Z"}}])])

        manager = _make_manager(RootlyResumeConfig(next_url=resume_url))
        rows = _rows(_source(manager=manager))

        # Starts at the resumed URL, not the freshly-built first page.
        assert rows == [{"id": "9", "title": "Z"}]
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @parameterized.expand(
        [
            ("empty_collection", False),
            # A body without `data` is treated as an empty page (JSON:API always carries `data`).
            ("missing_data_key", True),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, _name: str, drop_data: bool, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], drop_data=drop_data)])

        manager = _make_manager()
        assert _rows(_source(manager=manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestIncrementalParams:
    @parameterized.expand(
        [
            (
                "incremental_endpoint_sorts_and_filters_on_watermark",
                "incidents",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"page[size]": 100, "sort": "updated_at", "filter[updated_at][gt]": "2026-03-04T02:58:14+00:00"},
            ),
            (
                "incremental_first_sync_sorts_without_filter",
                "incidents",
                True,
                None,
                {"page[size]": 100, "sort": "updated_at"},
            ),
            (
                "incremental_disabled_has_no_sort_or_filter",
                "incidents",
                False,
                datetime(2026, 3, 4),
                {"page[size]": 100},
            ),
            (
                "full_refresh_endpoint_never_sorts_or_filters",
                "users",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"page[size]": 100},
            ),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_initial_request_params(
        self,
        _name: str,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_params: dict[str, Any],
        MockSession,
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1", "attributes": {}}])])

        _rows(
            _source(
                endpoint=endpoint,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
                incremental_field="updated_at",
            )
        )

        assert snapshots[0]["params"] == expected_params

    @freeze_time("2026-06-15T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_future_cursor_is_clamped(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1", "attributes": {}}])])

        _rows(
            _source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2027, 2, 5, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert snapshots[0]["params"]["filter[updated_at][gt]"] == "2026-06-15T12:00:00+00:00"


class TestHeadersAndAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_json_api_accept_header_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1", "attributes": {}}])])

        _rows(_source())
        assert session.headers.get("Accept") == ROOTLY_JSON_API_MEDIA_TYPE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_auth_is_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        auths: list[Any] = []

        def _prepare(request: Any) -> mock.MagicMock:
            auths.append(request.auth)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": "1", "attributes": {}}])]

        _rows(_source())

        # The token flows through the framework auth (so it's redacted from logs), not a
        # hand-built Authorization header.
        prepared = mock.MagicMock()
        prepared.headers = {}
        auths[0](prepared)
        assert prepared.headers["Authorization"] == "Bearer rootly_test"


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(ROOTLY_SESSION_PATCH)
    def test_returns_status_code(self, _name: str, status_code: int, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert probe_credentials("rootly_test", "incidents") == status_code

    @mock.patch(ROOTLY_SESSION_PATCH)
    def test_connection_failure_returns_none(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = Exception("boom")
        assert probe_credentials("rootly_test") is None

    @mock.patch(ROOTLY_SESSION_PATCH)
    def test_probes_endpoint_path_with_bearer_token(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("rootly_test", "incidents")

        url = session.get.call_args.args[0]
        assert url == f"{ROOTLY_BASE_URL}/incidents?page%5Bsize%5D=1"
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer rootly_test"

    @mock.patch(ROOTLY_SESSION_PATCH)
    def test_defaults_to_users_probe(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("rootly_test")

        assert session.get.call_args.args[0] == f"{ROOTLY_BASE_URL}/users?page%5Bsize%5D=1"
