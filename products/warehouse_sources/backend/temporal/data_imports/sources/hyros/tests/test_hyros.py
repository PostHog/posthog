import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.hyros import (
    HyrosResumeConfig,
    _format_hyros_date,
    hyros_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hyros module.
HYROS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hyros.hyros.make_tracked_session"
)


class _FakeResumeManager(ResumableSourceManager[HyrosResumeConfig]):
    def __init__(self, state: HyrosResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[HyrosResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> HyrosResumeConfig | None:
        return self.state

    def save_state(self, data: HyrosResumeConfig) -> None:
        self.saved.append(data)


class TestFormatHyrosDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14-05:00", "2026-03-04T02:58:14-05:00"),
            ("none_passthrough", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_hyros_date(value) == expected


def _response(result: list[dict[str, Any]] | None, next_page_id: str | None = None, drop_key: bool = False) -> Response:
    body: dict[str, Any] = {"request_id": "req-1"}
    if not drop_key:
        body["result"] = result or []
    if next_page_id is not None:
        body["nextPageId"] = next_page_id
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: ResumableSourceManager[HyrosResumeConfig], **kwargs: Any):
    return hyros_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=kwargs.pop("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.pop("db_incremental_field_last_value", None),
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestHyrosSourcePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_next_page_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], next_page_id="cursor-1"),
                _response([{"id": "3"}]),
            ],
        )

        rows = _rows(_source("Leads", _FakeResumeManager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://api.hyros.com/v1/api/v1.0/leads"
        assert snapshots[0]["params"] == {"pageSize": 250}
        assert snapshots[1]["params"] == {"pageSize": 250, "pageId": "cursor-1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_api_key_header(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("Stages", _FakeResumeManager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.api_key == "key"
        assert auth.name == "API-Key"
        assert auth.location == "header"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession) -> None:
        # A redirect off the validated Hyros host would carry the API-Key header with it to an
        # attacker-controlled origin; the client must refuse to follow it (credential-leak guard).
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])

        _rows(_source("Stages", _FakeResumeManager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], next_page_id="cursor-1"),
                _response([{"id": "2"}]),
            ],
        )

        manager = _FakeResumeManager()
        _rows(_source("Leads", manager))

        assert manager.saved == [HyrosResumeConfig(cursor="cursor-1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "2"}])])

        rows = _rows(_source("Leads", _FakeResumeManager(HyrosResumeConfig(cursor="cursor-1"))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["pageId"] == "cursor-1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_key_stops_quietly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_key=True)])

        rows = _rows(_source("Sources", _FakeResumeManager()))

        assert rows == []
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("Leads", "updatedFromDate"),
            ("Sales", "fromDate"),
            ("Calls", "fromDate"),
            ("Subscriptions", "fromDate"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_sends_expected_date_param(self, endpoint, param_name, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                endpoint,
                _FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"][param_name] == "2026-03-04T02:58:14+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters_by_date(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                "Stages",
                _FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"] == {"pageSize": 250}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_without_cursor_omits_date_param(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                "Leads", _FakeResumeManager(), should_use_incremental_field=True, db_incremental_field_last_value=None
            )
        )

        assert snapshots[0]["params"] == {"pageSize": 250}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_shape_by_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"name": "!tag1", "amount": 3}])])

        rows = _rows(_source("Tags", _FakeResumeManager()))

        assert rows == [{"name": "!tag1", "amount": 3}]


class TestValidateCredentials:
    @mock.patch(HYROS_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") == (True, 200)

    @mock.patch(HYROS_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") == (False, 401)

    @mock.patch(HYROS_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") == (False, None)

    @mock.patch(HYROS_SESSION_PATCH)
    def test_probes_user_info_with_api_key_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.hyros.com/v1/api/v1.0/user-info"
        assert call.kwargs["headers"]["API-Key"] == "key"
        assert call.kwargs["allow_redirects"] is False
