import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.folk import (
    FolkResumeConfig,
    FolkUntrustedURLError,
    _validate_pagination_url,
    folk_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.settings import FOLK_BASE_URL

# folk_source lets the RESTClient build its own tracked session, so the transport is mocked at the
# framework seam; the credential probe builds its session inside the folk module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
PROBE_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.folk.folk.make_tracked_session"


def _response(items: list[dict[str, Any]] | None, next_url: str | None = None) -> Response:
    pagination: dict[str, Any] = {"nextLink": next_url} if next_url else {}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"data": {"items": items or [], "pagination": pagination}}).encode()
    return resp


def _make_manager(resume_state: FolkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    # The paginator mutates request.url/params in place across pages, so snapshot each request at
    # prepare time instead of inspecting it after the run.
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str = "people",
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
):
    return folk_source(
        api_key="folk_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidatePaginationUrl:
    def test_api_origin_url_is_returned_unchanged(self) -> None:
        url = "https://api.folk.app/v1/people?limit=100&cursor=eyJvZmZzZXQiOjEwMH0%3D"
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/v1/people?cursor=x"),
            ("http_downgrade", "http://api.folk.app/v1/people?cursor=x"),
            ("userinfo_confusion", "https://api.folk.app@evil.example.com/v1/people"),
            ("wrong_path", "https://api.folk.app/steal-token"),
        ]
    )
    def test_off_origin_urls_are_refused(self, _name: str, url: str) -> None:
        # A poisoned resume state or hostile response must not retarget the bearer-token request.
        with pytest.raises(FolkUntrustedURLError):
            _validate_pagination_url(url)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_reads_the_items_envelope(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://api.folk.app/v1/people?limit=100&cursor=abc"
        snapshots = _wire(
            session,
            [
                _response([{"id": "per_1", "fullName": "Alice"}], next_url=second),
                _response([{"id": "per_2", "fullName": "Bob"}]),
            ],
        )

        rows = _rows(_source())

        assert rows == [{"id": "per_1", "fullName": "Alice"}, {"id": "per_2", "fullName": "Bob"}]
        assert snapshots[0]["url"] == f"{FOLK_BASE_URL}/v1/people"
        assert snapshots[0]["params"] == {"limit": 100}
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == second
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_except_the_last(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://api.folk.app/v1/people?limit=100&cursor=abc"
        _wire(session, [_response([{"id": "per_1"}], next_url=second), _response([{"id": "per_2"}])])

        manager = _make_manager()
        _rows(_source(manager=manager))

        # State saved once (pointing at the second page) so a crash re-yields that page; nothing
        # is saved after the final page (no nextLink).
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FolkResumeConfig(next_url=second)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://api.folk.app/v1/people?limit=100&cursor=page3"
        snapshots = _wire(session, [_response([{"id": "per_9"}])])

        manager = _make_manager(FolkResumeConfig(next_url=resume_url))
        rows = _rows(_source(manager=manager))

        # Starts at the resumed URL, not the freshly-built first page.
        assert rows == [{"id": "per_9"}]
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        assert _rows(_source(manager=manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_origin_next_link_is_refused(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "per_1"}], next_url="https://evil.example.com/v1/people?cursor=x")])

        with pytest.raises(FolkUntrustedURLError):
            _rows(_source())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_poisoned_resume_url_is_refused(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(FolkResumeConfig(next_url="https://evil.example.com/v1/people"))
        with pytest.raises(FolkUntrustedURLError):
            _rows(_source(manager=manager))
        # Refused before any request carries the bearer token off-origin.
        assert session.send.call_count == 0


class TestUnknownEndpoint:
    def test_unknown_endpoint_raises_a_retryable_unknown_resource_error(self) -> None:
        # A web pod can offer a table this worker's catalog doesn't know yet; the named error is
        # classified retryable so the sync recovers once the rollout finishes.
        with pytest.raises(UnknownResourceError):
            _source(endpoint="deals")


class TestBearerAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_auth_is_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        auths: list[Any] = []

        def _prepare(request: Any) -> mock.MagicMock:
            auths.append(request.auth)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": "per_1"}])]

        _rows(_source())

        # The key flows through the framework auth (so it's redacted from logs), not a hand-built
        # Authorization header.
        prepared = mock.MagicMock()
        prepared.headers = {}
        auths[0](prepared)
        assert prepared.headers["Authorization"] == "Bearer folk_test"


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(PROBE_SESSION_PATCH)
    def test_returns_status_code(self, _name: str, status_code: int, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert probe_credentials("folk_test") == status_code

    @mock.patch(PROBE_SESSION_PATCH)
    def test_connection_failure_returns_none(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = Exception("boom")
        assert probe_credentials("folk_test") is None

    @mock.patch(PROBE_SESSION_PATCH)
    def test_default_probe_is_the_current_user_with_bearer_token(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("folk_test")

        assert session.get.call_args.args[0] == f"{FOLK_BASE_URL}/v1/users/me"
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer folk_test"

    @mock.patch(PROBE_SESSION_PATCH)
    def test_schema_probe_hits_the_endpoint_path(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.return_value = mock.MagicMock(status_code=200)

        probe_credentials("folk_test", "companies")

        # Probing the endpoint's own path checks access to that resource, one row only.
        assert session.get.call_args.args[0] == f"{FOLK_BASE_URL}/v1/companies?limit=1"
