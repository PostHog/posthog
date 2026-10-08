import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Optional

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    ENDPOINTS,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.solarwinds_service_desk import (
    SolarwindsServiceDeskResumeConfig,
    _format_updated_from,
    _unwrap_row,
    base_url,
    solarwinds_service_desk_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the solarwinds module.
SWSD_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk"
    ".solarwinds_service_desk.make_tracked_session"
)


def _response(items: Optional[list[Any]], *, total_pages: Optional[int] = None, non_list: bool = False) -> Response:
    resp = Response()
    resp.status_code = 200
    body: Any = {"error": "weird"} if non_list else (items or [])
    resp._content = json.dumps(body).encode()
    if total_pages is not None:
        resp.headers["X-Total-Pages"] = str(total_pages)
    return resp


def _make_manager(resume_state: Optional[SolarwindsServiceDeskResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
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


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    session: mock.MagicMock,
    manager: mock.MagicMock,
    responses: list[Response],
    endpoint: str = "incidents",
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = _wire(session, responses)
    rows = _rows(
        solarwinds_service_desk_source(
            region="us",
            api_token="swsd-token",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
            **kwargs,
        )
    )
    return rows, params


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_does_not_stop_pagination(self, MockSession: mock.MagicMock) -> None:
        # A page smaller than PER_PAGE must not be treated as the end: the server may clamp
        # `per_page`, so only an empty page or the X-Total-Pages header terminates the crawl.
        session = MockSession.return_value
        manager = _make_manager()
        rows, params = _run(
            session,
            manager,
            [_response([{"id": 1}]), _response([{"id": 2}]), _response([])],
        )
        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 3
        assert [p["page"] for p in params] == [1, 2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_with_saved_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(SolarwindsServiceDeskResumeConfig(next_page=3, updated_from="2026-01-01T00:00"))
        rows, params = _run(
            session,
            manager,
            [_response([{"id": 9}], total_pages=3)],
            # A resumed run must reuse the persisted filter, not recompute one from this watermark.
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-02-02T00:00:00Z",
        )
        assert rows == [{"id": 9}]
        assert params[0]["page"] == 3
        assert params[0]["updated_from"] == "2026-01-01T00:00"

    @parameterized.expand(
        [
            ("full_refresh_endpoint", "users", True, datetime(2026, 1, 5, tzinfo=UTC)),
            ("incremental_disabled", "incidents", False, datetime(2026, 1, 5, tzinfo=UTC)),
            ("no_watermark", "incidents", True, None),
            ("unparseable_watermark", "incidents", True, "not a datetime"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_updated_from_param(
        self, _name: str, endpoint: str, use_incremental: bool, watermark: Any, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _, params = _run(
            session,
            _make_manager(),
            [_response([])],
            endpoint=endpoint,
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=watermark,
        )
        assert "updated_from" not in params[0]


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 5, 8, 30, 59, tzinfo=UTC), "2026-01-05T08:30"),
            ("aware_offset", datetime(2026, 1, 5, 9, 30, tzinfo=timezone(timedelta(hours=1))), "2026-01-05T08:30"),
            ("naive_treated_as_utc", datetime(2026, 1, 5, 8, 30), "2026-01-05T08:30"),
            ("iso_string", "2026-01-05T08:30:59.000+00:00", "2026-01-05T08:30"),
            ("date", date(2026, 1, 5), "2026-01-05T00:00"),
            ("garbage_string", "not a datetime", None),
            ("integer", 12345, None),
            ("none", None, None),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert _format_updated_from(value) == expected


class TestUnwrapRow:
    @parameterized.expand(
        [
            ("wrapped", {"user": {"id": 1, "name": "A"}}, "user", {"id": 1, "name": "A"}),
            ("bare_record", {"id": 2, "name": "B"}, "user", {"id": 2, "name": "B"}),
            # A single-key dict whose value isn't a record is a real record that merely has one field.
            ("wrapper_key_not_a_record", {"user": "not a record", "id": 3}, "user", {"user": "not a record", "id": 3}),
        ]
    )
    def test_normalizes_documented_shapes(
        self, _name: str, item: dict[str, Any], wrapper_key: str, expected: dict[str, Any]
    ) -> None:
        assert _unwrap_row(item, wrapper_key) == expected


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.samanage.com"),
            ("eu", "https://apieu.samanage.com"),
            ("au", "https://apiau.samanage.com"),
            (None, "https://api.samanage.com"),
            ("unknown", "https://api.samanage.com"),
        ]
    )
    def test_base_url_per_region(self, region: Optional[str], expected: str) -> None:
        assert base_url(region) == expected


class TestValidateCredentials:
    @staticmethod
    def _wire_status(mock_session: mock.MagicMock, response_or_exc: Any) -> None:
        session = mock.MagicMock()
        if isinstance(response_or_exc, Exception):
            session.get.side_effect = response_or_exc
        else:
            session.get.return_value = response_or_exc
        mock_session.return_value = session

    @parameterized.expand(
        [
            ("ok_at_create", 200, None, True, None),
            ("bad_token_at_create", 401, None, False, "Invalid SolarWinds Service Desk API token"),
            # A 403 with a genuine token must not block source-create, but must fail a
            # schema-scoped probe so the user sees which table their role can't read.
            ("forbidden_at_create", 403, None, True, None),
            (
                "forbidden_for_schema",
                403,
                "/incidents.json",
                False,
                "Your SolarWinds Service Desk token does not have permission to read this resource",
            ),
            ("server_error", 500, None, False, "SolarWinds Service Desk returned HTTP 500"),
        ]
    )
    @mock.patch(SWSD_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        path: Optional[str],
        expected_valid: bool,
        expected_message: Optional[str],
        mock_session: mock.MagicMock,
    ) -> None:
        self._wire_status(mock_session, mock.MagicMock(status_code=status))
        assert validate_credentials("us", "swsd-token", path) == (expected_valid, expected_message)

    @mock.patch(SWSD_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        self._wire_status(mock_session, ConnectionError("boom"))
        assert validate_credentials("us", "swsd-token") == (False, "Could not connect to SolarWinds Service Desk")


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, _MockSession: mock.MagicMock) -> None:
        config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]
        response = solarwinds_service_desk_source(
            region="us",
            api_token="swsd-token",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Ordering is undocumented, so the watermark must only commit after a completed sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # updated_at-style partition keys rewrite partitions on every sync.
        assert all(
            config.partition_key in (None, "created_at") for config in SOLARWINDS_SERVICE_DESK_ENDPOINTS.values()
        )
        assert set(SOLARWINDS_SERVICE_DESK_ENDPOINTS) == set(ENDPOINTS)
