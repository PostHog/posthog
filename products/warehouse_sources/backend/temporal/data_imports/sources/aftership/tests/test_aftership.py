import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.aftership import (
    API_KEY_HEADER,
    AftershipResumeConfig,
    _to_aftership_datetime,
    aftership_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.settings import (
    DEFAULT_VERSION,
    PAGE_SIZE,
)

BASE_URL = f"https://api.aftership.com/tracking/{DEFAULT_VERSION}"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.aftership.aftership.validate_via_probe"


def _response(
    key: str,
    items: Optional[list[dict[str, Any]]] = None,
    *,
    next_cursor: Optional[str] = None,
    status_code: int = 200,
) -> Response:
    data: dict[str, Any] = {key: items or []}
    if next_cursor is not None:
        data["pagination"] = {"next_cursor": next_cursor, "has_next_page": True}
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{BASE_URL}/trackings"
    resp._content = json.dumps({"meta": {"code": 200}, "data": data}).encode()
    return resp


def _make_manager(resume_state: Optional[AftershipResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    # ``request.params`` is one dict mutated in place across pages, so snapshot a copy while each
    # request is prepared rather than reading it after the run.
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return aftership_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestToAftershipDatetime:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC), "2026-01-15T12:30:45+00:00"),
            ("naive_treated_as_utc", datetime(2026, 1, 15, 12, 30, 45), "2026-01-15T12:30:45+00:00"),
            (
                "other_offset_converted",
                datetime(2026, 1, 15, 20, 30, 45, tzinfo=timezone(timedelta(hours=8))),
                "2026-01-15T12:30:45+00:00",
            ),
            (
                "microseconds_dropped",
                datetime(2026, 1, 15, 12, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T12:30:45+00:00",
            ),
            ("zulu_string_rewritten", "2026-01-15T12:30:45Z", "2026-01-15T12:30:45+00:00"),
            ("offset_string", "2026-01-15T20:30:45+08:00", "2026-01-15T12:30:45+00:00"),
            ("garbage_string", "not-a-date", None),
            ("non_datetime_type", 12345, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: Optional[str]) -> None:
        # AfterShip validates these params against ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$,
        # so a trailing Z or fractional seconds is a 400.
        assert _to_aftership_datetime(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_cursor_from_nested_envelope(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, urls = _wire(
            session,
            [
                _response("trackings", [{"id": "1"}], next_cursor="cur-1"),
                _response("trackings", [{"id": "2"}]),
            ],
        )

        rows = _rows(_source("trackings", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert urls[0] == f"{BASE_URL}/trackings"
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "cursor": "cur-1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_cursor_ends_pagination_without_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response("trackings", [{"id": "a"}])])

        manager = _make_manager()
        rows = _rows(_source("trackings", manager))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_couriers_is_single_page_and_never_sends_a_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # A next_cursor in the body must not restart pagination for an endpoint that has none.
        params, urls = _wire(session, [_response("couriers", [{"slug": "usps"}], next_cursor="cur-1")])

        rows = _rows(_source("couriers", _make_manager()))

        assert [r["slug"] for r in rows] == ["usps"]
        assert session.send.call_count == 1
        assert urls[0] == f"{BASE_URL}/couriers"
        assert params[0] == {}


class TestIncrementalFiltering:
    @parameterized.expand(
        [
            ("updated_at", "updated_at", "updated_at_min"),
            ("created_at", "created_at", "created_at_min"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_incremental_field_picks_the_server_side_filter(
        self, _name: str, incremental_field_name: str, expected_param: str, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("trackings", [{"id": "1"}])])

        _rows(
            _source(
                "trackings",
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field_name=incremental_field_name,
                db_incremental_field_last_value=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
            )
        )

        assert params[0][expected_param] == "2026-01-15T12:00:00+00:00"
        assert len([key for key in params[0] if key.endswith("_min")]) == 1

    @parameterized.expand(
        [
            ("unmapped_field_on_incremental_endpoint", "trackings", "shipment_delivery_date"),
            ("full_refresh_endpoint", "courier_connections", "updated_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_sent_when_the_field_has_no_server_side_param(
        self, _name: str, endpoint: str, incremental_field_name: str, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response(endpoint, [])])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field_name=incremental_field_name,
                db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
            )
        )

        assert not [key for key in params[0] if key.endswith("_min")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_filter_is_resent_on_every_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [_response("trackings", [{"id": "1"}], next_cursor="cur-1"), _response("trackings", [{"id": "2"}])],
        )

        _rows(
            _source(
                "trackings",
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field_name="updated_at",
                db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
            )
        )

        assert all(page["updated_at_min"] == "2026-01-15T00:00:00+00:00" for page in params)


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_and_window_after_yielding_each_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response("trackings", [{"id": "1"}], next_cursor="cur-1"), _response("trackings", [{"id": "2"}])],
        )

        manager = _make_manager()
        _rows(
            _source(
                "trackings",
                manager,
                should_use_incremental_field=True,
                incremental_field_name="updated_at",
                db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
            )
        )

        manager.save_state.assert_called_once_with(
            AftershipResumeConfig(cursor="cur-1", incremental_start="2026-01-15T00:00:00+00:00")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor_and_reuses_the_saved_window(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("trackings", [{"id": "9"}])])

        manager = _make_manager(AftershipResumeConfig(cursor="cur-8", incremental_start="2026-01-01T00:00:00+00:00"))
        rows = _rows(
            _source(
                "trackings",
                manager,
                should_use_incremental_field=True,
                incremental_field_name="updated_at",
                # The watermark advanced from committed batches; narrowing the window mid-walk
                # would leave the saved cursor pointing outside the filtered result set.
                db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )

        assert [r["id"] for r in rows] == ["9"]
        assert params[0]["cursor"] == "cur-8"
        assert params[0]["updated_at_min"] == "2026-01-01T00:00:00+00:00"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("trackings", "trackings", ["id"], ["created_at"]),
            ("couriers", "couriers", ["slug"], None),
            ("courier_connections", "courier_connections", ["id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, _name: str, endpoint: str, expected_keys: list[str], expected_partition_keys: Optional[list[str]]
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_keys == expected_partition_keys
        # AfterShip documents no ordering and offers no sort param, so the watermark is only
        # committed once at the end of the sync.
        assert response.sort_mode == "desc"


class TestRequestShape:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_sent_in_the_as_api_key_header(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.headers = {}
        prepared: list[Any] = []

        def _prepare(request: Any) -> mock.MagicMock:
            fake = mock.MagicMock()
            fake.headers = {}
            fake.url = request.url
            # `auth` is a callable applied to the prepared request by the framework.
            prepared.append(request.auth(fake) if request.auth else fake)
            return fake

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response("trackings", [])]

        _rows(_source("trackings", _make_manager()))

        # The legacy `aftership-api-key` header stopped working at API version 2023-10.
        assert prepared[0].headers[API_KEY_HEADER] == "key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_version_is_a_path_segment(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _params, urls = _wire(session, [_response("trackings", [])])

        _rows(_source("trackings", _make_manager(), api_version="2026-01"))

        assert urls[0] == "https://api.aftership.com/tracking/2026-01/trackings"

    @parameterized.expand([(401,), (403,)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_errors_raise_a_matchable_http_error(self, status_code: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response("trackings", [], status_code=status_code)])

        with pytest.raises(HTTPError) as exc:
            _rows(_source("trackings", _make_manager()))
        assert f"{status_code} Client Error" in str(exc.value)


class TestCourierConnectionRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_carrier_credentials_never_reach_the_warehouse(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    "courier_connections",
                    [
                        {
                            "id": "conn-1",
                            "courier_slug": "dhl-api",
                            "credentials": {"api_key": "carrier-secret", "password": "hunter2"},
                            "created_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                )
            ],
        )

        rows = _rows(_source("courier_connections", _make_manager()))

        assert rows == [{"id": "conn-1", "courier_slug": "dhl-api", "created_at": "2026-01-01T00:00:00+00:00"}]


class TestCheckAccess:
    @parameterized.expand(
        [
            ("token_only", None, f"{BASE_URL}/trackings?limit=1"),
            ("cursor_endpoint", "courier_connections", f"{BASE_URL}/courier-connections?limit=1"),
            ("single_page_endpoint", "couriers", f"{BASE_URL}/couriers"),
        ]
    )
    @mock.patch(PROBE_PATCH)
    def test_probe_url_per_schema(
        self, _name: str, schema_name: Optional[str], expected_url: str, mock_probe: mock.MagicMock
    ) -> None:
        mock_probe.return_value = (True, 200)

        assert check_access("key", schema_name) == (True, 200)
        assert mock_probe.call_args.args[1] == expected_url

    @mock.patch(PROBE_PATCH)
    def test_probe_does_not_follow_redirects(self, mock_probe: mock.MagicMock) -> None:
        mock_probe.return_value = (True, 200)

        check_access("key")

        # The key rides a custom header, which requests would replay to a redirect target.
        assert mock_probe.call_args.kwargs["allow_redirects"] is False
        assert mock_probe.call_args.kwargs["headers"] == {API_KEY_HEADER: "key"}
