import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack import (
    BETTER_STACK_BASE_URL,
    BetterStackResumeConfig,
    BetterStackUntrustedURLError,
    _flatten_item,
    _format_from_date,
    _validate_pagination_url,
    better_stack_source,
    probe_credentials,
)

# better_stack builds its own capture=False session and passes it into the RESTClient.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"pagination": {"next": next_url}}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BetterStackResumeConfig | None = None) -> mock.MagicMock:
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


def _source(
    endpoint: str = "incidents",
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
):
    return better_stack_source(
        api_token="bs_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatFromDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04", "2026-03-04"),
        ]
    )
    def test_formats_as_date_only(self, _name: str, value: object, expected: str) -> None:
        # Better Stack's `from` filter takes YYYY-MM-DD, not a full timestamp.
        assert _format_from_date(value) == expected


class TestFlattenItem:
    def test_attributes_hoisted_to_root_and_id_type_kept(self) -> None:
        item = {
            "id": "123",
            "type": "incident",
            "attributes": {"name": "API", "cause": "Status 500", "started_at": "2026-01-01T00:00:00Z"},
        }
        assert _flatten_item(item) == {
            "id": "123",
            "type": "incident",
            "name": "API",
            "cause": "Status 500",
            "started_at": "2026-01-01T00:00:00Z",
        }

    def test_missing_attributes_is_safe(self) -> None:
        assert _flatten_item({"id": "123", "type": "incident"}) == {"id": "123", "type": "incident"}


class TestValidatePaginationUrl:
    def test_api_origin_url_is_returned_unchanged(self) -> None:
        url = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/v3/incidents"),
            ("http_downgrade", "http://uptime.betterstack.com/api/v3/incidents"),
            ("userinfo_confusion", "https://uptime.betterstack.com@evil.example.com/api/v3/incidents"),
            ("wrong_path", "https://uptime.betterstack.com/steal-token"),
        ]
    )
    def test_off_origin_urls_are_refused(self, _name: str, url: str) -> None:
        # A poisoned resume state or hostile response must not retarget the bearer-token request.
        with pytest.raises(BetterStackUntrustedURLError):
            _validate_pagination_url(url)


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_follows_pagination_next_and_flattens(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        snapshots = _wire(
            session,
            [
                _response([{"id": "1", "type": "incident", "attributes": {"cause": "Timeout"}}], next_url=second),
                _response([{"id": "2", "type": "incident", "attributes": {"cause": "Status 500"}}]),
            ],
        )

        rows = _rows(_source())

        assert rows == [
            {"id": "1", "type": "incident", "cause": "Timeout"},
            {"id": "2", "type": "incident", "cause": "Status 500"},
        ]
        assert snapshots[0]["url"] == f"{BETTER_STACK_BASE_URL}/v3/incidents"
        assert snapshots[0]["params"] == {"per_page": 50}
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == second
        assert snapshots[1]["params"] == {}

    @mock.patch(SESSION_PATCH)
    def test_saves_state_after_each_page_except_the_last(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
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
        assert manager.save_state.call_args.args[0] == BetterStackResumeConfig(next_url=second)

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://uptime.betterstack.com/api/v3/incidents?page=3&per_page=50"
        snapshots = _wire(session, [_response([{"id": "9", "attributes": {"cause": "Z"}}])])

        manager = _make_manager(BetterStackResumeConfig(next_url=resume_url))
        rows = _rows(_source(manager=manager))

        # Starts at the resumed URL, not the freshly-built first page.
        assert rows == [{"id": "9", "cause": "Z"}]
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @parameterized.expand(
        [
            ("empty_collection", False),
            # Old envelope always carries `data`; a body without it is treated as an empty page.
            ("missing_data_key", True),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, _name: str, drop_data: bool, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], drop_data=drop_data)])

        manager = _make_manager()
        assert _rows(_source(manager=manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_off_origin_next_url_is_refused(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response([{"id": "1", "attributes": {}}], next_url="https://evil.example.com/api/v3/incidents?page=2")],
        )

        with pytest.raises(BetterStackUntrustedURLError):
            _rows(_source())

    @mock.patch(SESSION_PATCH)
    def test_poisoned_resume_url_is_refused(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(BetterStackResumeConfig(next_url="https://evil.example.com/api/v3/incidents"))
        with pytest.raises(BetterStackUntrustedURLError):
            _rows(_source(manager=manager))
        # Refused before any request carries the bearer token off-origin.
        assert session.send.call_count == 0


class TestIncrementalParams:
    @parameterized.expand(
        [
            (
                "incremental_endpoint_filters_from_watermark_date",
                "incidents",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"per_page": 50, "from": "2026-03-04"},
            ),
            ("incremental_first_sync_has_no_filter", "incidents", True, None, {"per_page": 50}),
            ("incremental_disabled_has_no_filter", "incidents", False, datetime(2026, 3, 4), {"per_page": 50}),
            (
                "full_refresh_endpoint_never_filters",
                "monitors",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"per_page": 250},
            ),
        ]
    )
    @mock.patch(SESSION_PATCH)
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
            )
        )

        assert snapshots[0]["params"] == expected_params

    @freeze_time("2026-06-15T12:00:00Z")
    @mock.patch(SESSION_PATCH)
    def test_future_cursor_is_clamped(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1", "attributes": {}}])])

        _rows(
            _source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2027, 2, 5, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["from"] == "2026-06-15"


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(SESSION_PATCH)
    def test_returns_status_code(self, _name: str, status_code: int, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert probe_credentials("bs_test", "incidents") == status_code

    @mock.patch(SESSION_PATCH)
    def test_connection_failure_returns_none(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = Exception("boom")
        assert probe_credentials("bs_test") is None

    @mock.patch(SESSION_PATCH)
    def test_probes_endpoint_path_with_bearer_token(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("bs_test", "incidents")

        url = session.get.call_args.args[0]
        assert url == f"{BETTER_STACK_BASE_URL}/v3/incidents?per_page=1"
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer bs_test"

    @mock.patch(SESSION_PATCH)
    def test_defaults_to_monitors_probe(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("bs_test")

        assert session.get.call_args.args[0] == f"{BETTER_STACK_BASE_URL}/v2/monitors?per_page=1"


class TestBearerAuth:
    @mock.patch(SESSION_PATCH)
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
        assert prepared.headers["Authorization"] == "Bearer bs_test"
