import json
from collections.abc import Callable
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify import (
    NetlifyCappedHeaderLinkPaginator,
    NetlifyHeaderLinkPaginator,
    NetlifyPageCapExceededError,
    NetlifyResumeConfig,
    NetlifyUntrustedURLError,
    netlify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import NETLIFY_ENDPOINTS

BASE = "https://api.netlify.com/api/v1"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the netlify module.
NETLIFY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify.make_tracked_session"
)


def _response(items: Any, next_url: str | None = None, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = "OK" if status < 400 else "Error"
    resp._content = json.dumps(items).encode()
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _manager(resume: NetlifyResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.Mock, responses: list[Response] | Callable[[str], Response]) -> list[dict[str, Any]]:
    """Drive a mock session. `request.params` is a single dict mutated in place across pages, so
    snapshot a copy at prepare_request time. A real session builds the prepared URL so callers can
    route responses by URL (fan-out sends a different child request per parent)."""
    session.headers = {}
    real = requests.Session()
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        prepared = real.prepare_request(request)
        snapshots.append({"url": prepared.url, "params": dict(request.params or {})})
        return prepared

    session.prepare_request.side_effect = _prepare
    if callable(responses):
        session.send.side_effect = lambda prepared, **_kw: responses(prepared.url)
    else:
        session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.Mock) -> Any:
    return netlify_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_checkpoints_after_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "a"}], next_url=f"{BASE}/sites?page=2&per_page=100"),
                _response([{"id": "b"}], next_url=None),
            ],
        )
        manager = _manager()
        rows = _rows(_source("sites", manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert snaps[0]["params"]["per_page"] == 100
        # The next-page URL is self-contained, so its params are dropped on the follow-up request.
        assert snaps[1]["params"] == {}
        # State saved once — after the first page, pointing at the second. The last page has no next
        # link, so nothing is saved for it.
        manager.save_state.assert_called_once_with(NetlifyResumeConfig(next_url=f"{BASE}/sites?page=2&per_page=100"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession) -> None:
        resume_url = f"{BASE}/sites?page=3&per_page=100"
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "c"}], next_url=None)])
        manager = _manager(NetlifyResumeConfig(next_url=resume_url))

        rows = _rows(_source("sites", manager))

        assert rows == [{"id": "c"}]
        assert snaps[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _manager()

        assert _rows(_source("sites", manager)) == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_strips_credential_fields_from_sites(self, MockSession) -> None:
        # A site object carries account credentials that must never reach the queryable table.
        session = MockSession.return_value
        site = {
            "id": "s1",
            "name": "acme",
            "password": "hunter2",
            "default_hooks_data": {"access_token": "secret-token", "type": "github"},
            "build_settings": {"env": {"STRIPE_KEY": "sk_live_x"}, "cmd": "build"},
        }
        _wire(session, [_response([site], next_url=None)])

        rows = _rows(_source("sites", _manager()))
        assert rows == [
            {
                "id": "s1",
                "name": "acme",
                "default_hooks_data": {"type": "github"},
                "build_settings": {"cmd": "build"},
            }
        ]


class TestUrlPinning:
    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/api/v1/sites?page=2"),
            ("scheme_downgrade", "http://api.netlify.com/api/v1/sites?page=2"),
        ]
    )
    def test_rejects_untrusted_next_url_from_link_header(self, _name: str, target: str) -> None:
        paginator = NetlifyHeaderLinkPaginator()
        response = _response([{"id": "a"}], next_url=target)
        with pytest.raises(NetlifyUntrustedURLError):
            paginator.update_state(response, [{"id": "a"}])

    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/api/v1/sites?page=2"),
            ("scheme_downgrade", "http://api.netlify.com/api/v1/sites?page=2"),
        ]
    )
    def test_rejects_untrusted_seeded_resume_url(self, _name: str, target: str) -> None:
        paginator = NetlifyHeaderLinkPaginator()
        with pytest.raises(NetlifyUntrustedURLError):
            paginator.set_resume_state({"next_url": target})


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_parent_site_id_and_checkpoints_fanout_state(self, MockSession) -> None:
        session = MockSession.return_value

        def route(url: str) -> Response:
            if url == f"{BASE}/sites?per_page=100":
                return _response([{"id": "s1"}], next_url=None)
            if url == f"{BASE}/sites/s1/builds?per_page=100":
                return _response([{"id": "b1"}], next_url=None)
            raise AssertionError(f"unexpected url: {url}")

        _wire(session, route)
        manager = _manager()
        rows = _rows(_source("builds", manager))

        # site_id is injected onto each build row (a build carries no site_id of its own).
        assert rows == [{"id": "b1", "site_id": "s1"}]
        # The final checkpoint records the parent as fully synced under its resolved child path.
        assert manager.save_state.call_args.args[0] == NetlifyResumeConfig(
            fanout_state={"completed": ["/sites/s1/builds"], "current": None, "child_state": None}
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_fan_out_reads_parent_slug(self, MockSession) -> None:
        session = MockSession.return_value

        def route(url: str) -> Response:
            if url == f"{BASE}/accounts":
                return _response([{"id": "acc-1", "slug": "acme"}], next_url=None)
            if url == f"{BASE}/acme/members":
                return _response([{"id": "u1", "email": "a@b.co"}], next_url=None)
            raise AssertionError(f"unexpected url: {url}")

        _wire(session, route)
        rows = _rows(_source("members", _manager()))

        # Members fan out over accounts keyed by the account slug, injected as account_slug.
        assert rows == [{"id": "u1", "email": "a@b.co", "account_slug": "acme"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_fanout_from_saved_state_skipping_completed_parent(self, MockSession) -> None:
        session = MockSession.return_value

        def route(url: str) -> Response:
            if url == f"{BASE}/sites?per_page=100":
                return _response([{"id": "s1"}, {"id": "s2"}], next_url=None)
            if url == f"{BASE}/sites/s2/builds?per_page=100":
                return _response([{"id": "b2"}], next_url=None)
            raise AssertionError(f"unexpected url: {url}")

        _wire(session, route)
        manager = _manager(
            NetlifyResumeConfig(fanout_state={"completed": ["/sites/s1/builds"], "current": None, "child_state": None})
        )
        rows = _rows(_source("builds", manager))

        # s1 is already completed, so only s2's builds are fetched on resume (merge dedupes s1).
        assert rows == [{"id": "b2", "site_id": "s2"}]


class TestPageCap:
    def test_capped_paginator_raises_when_parent_exceeds_cap(self) -> None:
        # Hitting the per-parent page cap must fail loudly rather than silently truncate the table.
        paginator = NetlifyCappedHeaderLinkPaginator(max_pages=2, context={"table": "builds"})
        page = [{"id": "x"}]
        resp = _response(page, next_url=f"{BASE}/sites/s1/builds?page=2")
        paginator.update_state(resp, page)  # page 1: under the cap
        with pytest.raises(NetlifyPageCapExceededError):
            paginator.update_state(resp, page)  # page 2: cap reached with more pages remaining

    def test_capped_paginator_stops_cleanly_when_no_more_pages(self) -> None:
        paginator = NetlifyCappedHeaderLinkPaginator(max_pages=2, context={"table": "builds"})
        page = [{"id": "x"}]
        # Exactly at the cap but no next link -> a complete table, not an overrun.
        paginator.update_state(_response(page, next_url=f"{BASE}/sites/s1/builds?page=2"), page)
        paginator.update_state(_response(page, next_url=None), page)
        assert paginator.has_next_page is False


class TestFailLoud:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises(self, MockSession) -> None:
        # A 401/403 is not retryable and must surface as an HTTPError the source maps to a message.
        session = MockSession.return_value
        _wire(session, [_response({"code": 401, "message": "Access Denied"}, status=401)])
        with pytest.raises(requests.HTTPError):
            _rows(_source("sites", _manager()))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(NETLIFY_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.Mock(status_code=status)
        assert validate_credentials("tok") is expected

    @mock.patch(NETLIFY_SESSION_PATCH)
    def test_exception_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError()
        assert validate_credentials("tok") is False


class TestNetlifySourceResponse:
    @parameterized.expand(list(NETLIFY_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = NETLIFY_ENDPOINTS[endpoint]
        response = _source(endpoint, _manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        # Partition config is present only for endpoints with a stable creation-time field.
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
