import json
import base64
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import (
    OwnerRezResumeConfig,
    _basic_auth_header,
    _build_params,
    _format_since_utc,
    ownerrez_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import (
    EPOCH,
    OWNERREZ_ENDPOINTS,
    PAGE_LIMIT,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the ownerrez module.
OWNERREZ_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez.make_tracked_session"
)


class TestFormatSinceUtc:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_since_utc(value)
        assert result == expected
        assert "+00:00" not in result


class TestBasicAuthHeader:
    def test_encodes_email_and_token(self) -> None:
        header = _basic_auth_header("host@example.com", "pt_key")
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
        assert decoded == "host@example.com:pt_key"


class TestBuildParams:
    def test_required_since_endpoint_defaults_to_epoch_on_first_sync(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Bookings"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"limit": PAGE_LIMIT, "since_utc": EPOCH}

    def test_required_since_endpoint_uses_cursor_when_present(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Bookings"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"limit": PAGE_LIMIT, "since_utc": "2026-03-04T02:58:14Z"}

    def test_required_since_endpoint_uses_epoch_when_not_incremental(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Bookings"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {"limit": PAGE_LIMIT, "since_utc": EPOCH}

    def test_optional_since_endpoint_omits_filter_with_no_cursor(self) -> None:
        # Quotes' since_utc isn't required by the API, so a first sync with no watermark fetches everything.
        params = _build_params(
            OWNERREZ_ENDPOINTS["Quotes"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"limit": PAGE_LIMIT}

    def test_optional_since_endpoint_filters_with_cursor(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Quotes"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"limit": PAGE_LIMIT, "since_utc": "2026-03-04T00:00:00Z"}

    def test_non_incremental_endpoint_never_filters(self) -> None:
        # Guests has no exposed timestamp column, so it never offers incremental sync — but the
        # API still requires created_since_utc on every request.
        params = _build_params(
            OWNERREZ_ENDPOINTS["Guests"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"limit": PAGE_LIMIT, "created_since_utc": EPOCH}

    def test_endpoint_without_since_param_never_filters(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Properties"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"limit": PAGE_LIMIT}


def _response(items: list[dict[str, Any]] | None, *, next_page_url: str | None = None) -> Response:
    body: dict[str, Any] = {"items": items or [], "limit": PAGE_LIMIT, "offset": 0, "next_page_url": next_page_url}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: OwnerRezResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "auth": request.auth,
                "headers": dict(request.headers or {}),
            }
        )
        # RESTClient checks the *prepared* request's URL against allowed_hosts before sending
        # (rest_client._check_allowed_host), so the stand-in prepared request needs a real URL
        # string here, not an auto-generated Mock attribute.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return ownerrez_source(
        email="host@example.com",
        api_key="pt_key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=None,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in cast(Any, source_response.items()) for row in page]


class TestOwnerrezSourceTransport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_url_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], next_page_url="https://api.ownerrez.com/v2/properties?offset=2"),
                _response([{"id": 3}], next_page_url=None),
            ],
        )

        rows = _rows(_source("Properties", _make_manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://api.ownerrez.com/v2/properties"
        assert snapshots[0]["params"] == {"limit": PAGE_LIMIT}
        # The second request follows the opaque next_page_url verbatim, with no re-appended params.
        assert snapshots[1]["url"] == "https://api.ownerrez.com/v2/properties?offset=2"
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_http_basic_with_email_as_username(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(_source("Properties", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, HttpBasicAuth)
        assert auth.username == "host@example.com"
        assert auth.password == "pt_key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_user_agent_header(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        _wire(session, [_response([{"id": 1}])])

        _rows(_source("Properties", _make_manager()))

        assert session.headers.get("User-Agent") == "PostHog Data Warehouse (+https://posthog.com)"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bookings_sends_epoch_since_utc_on_first_full_sync(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(_source("Bookings", _make_manager()))

        assert snapshots[0]["params"]["since_utc"] == EPOCH

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bookings_incremental_cursor_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(
            ownerrez_source(
                email="host@example.com",
                api_key="pt_key",
                endpoint="Bookings",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["since_utc"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], next_page_url="https://api.ownerrez.com/v2/properties?offset=1"),
                _response([{"id": 2}], next_page_url=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("Properties", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OwnerRezResumeConfig(
            next_url="https://api.ownerrez.com/v2/properties?offset=1"
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 2}], next_page_url=None)])

        rows = _rows(
            _source(
                "Properties",
                _make_manager(OwnerRezResumeConfig(next_url="https://api.ownerrez.com/v2/properties?offset=1")),
            )
        )

        assert [r["id"] for r in rows] == [2]
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == "https://api.ownerrez.com/v2/properties?offset=1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_items(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_page_url=None)])

        manager = _make_manager()
        rows = _rows(_source("Properties", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_write_disposition_is_merge_when_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = ownerrez_source(
            email="host@example.com",
            api_key="pt_key",
            endpoint="Bookings",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_utc"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_partitioning(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = _source("Guests", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @mock.patch(OWNERREZ_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("host@example.com", "pt_key") == (True, 200)

    @mock.patch(OWNERREZ_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("host@example.com", "pt_key") == (False, 401)

    @mock.patch(OWNERREZ_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("host@example.com", "pt_key") == (False, None)

    @mock.patch(OWNERREZ_SESSION_PATCH)
    def test_probes_properties_endpoint_with_basic_auth_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("host@example.com", "pt_key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.ownerrez.com/v2/properties?limit=1"
        decoded = base64.b64decode(call.kwargs["headers"]["Authorization"].removeprefix("Basic ")).decode()
        assert decoded == "host@example.com:pt_key"
        assert call.kwargs["headers"]["User-Agent"] == "PostHog Data Warehouse (+https://posthog.com)"
