import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.mighty_networks import (
    USER_AGENT,
    MightyNetworksResumeConfig,
    check_endpoint_access,
    mighty_networks_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.settings import PER_PAGE

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials / check_endpoint_access build their own tracked sessions in this module.
MIGHTY_NETWORKS_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.mighty_networks.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_data_key: bool = False,
    status_code: int = 200,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_data_key:
        body["data"] = items or []
    if total_pages is not None:
        body["meta"] = {"current_page": current_page or 1, "total_pages": total_pages}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: MightyNetworksResumeConfig | None = None) -> mock.MagicMock:
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
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return mighty_networks_source(
        api_key="key",
        network_id="1234",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestMightyNetworksSourceNonFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], current_page=1, total_pages=2),
                _response([{"id": 3}], current_page=2, total_pages=2),
            ],
        )

        rows = _rows(_source("Members", _make_manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        # total_pages=2 terminates after the last page — no extra empty-page request.
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://api.mn.co/admin/v1/networks/1234/members"
        assert snapshots[0]["params"] == {"per_page": PER_PAGE, "page": 1}
        assert snapshots[1]["params"] == {"per_page": PER_PAGE, "page": 2}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}], total_pages=1)])

        _rows(_source("Members", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_descriptive_user_agent(self, MockSession) -> None:
        # Mighty Networks blocks requests with no/generic User-Agent as bot traffic (HTTP 403 +
        # HTML challenge page). The client applies this as a session-level header.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], total_pages=1)])

        _rows(_source("Members", _make_manager()))

        assert session.headers["User-Agent"] == USER_AGENT

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], current_page=1, total_pages=2),
                _response([{"id": 2}], current_page=2, total_pages=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("Members", manager))

        # State is saved only while more pages remain (page 1 -> next_page 2), never on the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == MightyNetworksResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 2}], current_page=2, total_pages=2)])

        rows = _rows(_source("Members", _make_manager(MightyNetworksResumeConfig(next_page=2))))

        assert [r["id"] for r in rows] == [2]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("Spaces", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises(self, MockSession) -> None:
        # data_selector_required=True: a response shape change fails loud instead of silently
        # syncing zero rows.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data_key=True)])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source("Members", _make_manager()))

    @parameterized.expand(
        [
            ("Members", "/members"),
            ("Spaces", "/spaces"),
            ("Posts", "/posts"),
            ("Events", "/events"),
            ("Plans", "/plans"),
            ("Subscriptions", "/subscriptions"),
            ("Purchases", "/purchases"),
            ("Tags", "/tags"),
            ("Badges", "/badges"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_paths(self, endpoint: str, path: str, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([], total_pages=1)])

        _rows(_source(endpoint, _make_manager()))

        assert snapshots[0]["url"] == f"https://api.mn.co/admin/v1/networks/1234{path}"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_subscriptions_row_hoists_nested_id(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "member_id": 9,
                            "subscription": {"id": 55, "purchased_at": "2026-01-01T00:00:00Z"},
                        }
                    ],
                    total_pages=1,
                )
            ],
        )

        rows = _rows(_source("Subscriptions", _make_manager()))

        assert rows == [
            {
                "member_id": 9,
                "subscription": {"id": 55, "purchased_at": "2026-01-01T00:00:00Z"},
                "id": 55,
            }
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_purchases_row_hoists_nested_fields(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "member_id": 9,
                            "purchase": {
                                "id": 77,
                                "created_at": "2026-01-01T00:00:00Z",
                                "updated_at": "2026-01-02T00:00:00Z",
                            },
                        }
                    ],
                    total_pages=1,
                )
            ],
        )

        rows = _rows(_source("Purchases", _make_manager()))

        assert rows[0]["id"] == 77
        assert rows[0]["created_at"] == "2026-01-01T00:00:00Z"
        assert rows[0]["updated_at"] == "2026-01-02T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_row_is_not_flattened(self, MockSession) -> None:
        # Only Subscriptions and Purchases need the nested-id fixup.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1, "email": "a@example.com"}], total_pages=1)])

        rows = _rows(_source("Members", _make_manager()))

        assert rows == [{"id": 1, "email": "a@example.com"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioning_uses_created_at(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total_pages=1)])

        response = _source("Members", _make_manager())

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.primary_keys == ["id"]


class TestValidateCredentials:
    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key", "1234") == (True, 200)

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key", "1234") == (False, 401)

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "1234") == (False, None)

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_probes_me_endpoint_with_bearer_header_and_user_agent(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", "1234")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.mn.co/admin/v1/networks/1234/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"
        assert call.kwargs["headers"]["User-Agent"] == USER_AGENT


class TestCheckEndpointAccess:
    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_reachable_endpoint_returns_none(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert check_endpoint_access("key", "1234", "Members") is None

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_forbidden_returns_vendor_message(self, mock_session) -> None:
        response = mock.MagicMock(status_code=403)
        response.json.return_value = {
            "error": "forbidden",
            "message": "Token is missing the members scope",
            "status": 403,
        }
        mock_session.return_value.get.return_value = response

        assert check_endpoint_access("key", "1234", "Members") == "Token is missing the members scope"

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_forbidden_without_parseable_body_falls_back_to_generic_message(self, mock_session) -> None:
        response = mock.MagicMock(status_code=403)
        response.json.side_effect = ValueError("not json")
        mock_session.return_value.get.return_value = response

        assert check_endpoint_access("key", "1234", "Members") == (
            "Your Mighty Networks API token doesn't have permission to read this data."
        )

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("not_found", 404)])
    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_non_403_statuses_are_not_treated_as_permission_errors(self, _name, status_code, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert check_endpoint_access("key", "1234", "Members") is None

    @mock.patch(MIGHTY_NETWORKS_SESSION_PATCH)
    def test_transport_error_is_not_treated_as_permission_error(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert check_endpoint_access("key", "1234", "Members") is None
