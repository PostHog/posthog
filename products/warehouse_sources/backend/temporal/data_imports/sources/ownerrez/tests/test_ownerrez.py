import json
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import (
    OwnerRezResumeConfig,
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


class TestBuildParams:
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


class TestValidateCredentials:
    @mock.patch(OWNERREZ_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("host@example.com", "pt_key") == (True, 200)
