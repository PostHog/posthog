import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.netlify import (
    NetlifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import netlify as netlify_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify import (
    NetlifyCappedHeaderLinkPaginator,
    NetlifyHeaderLinkPaginator,
    NetlifyPageCapExceededError,
    NetlifyResumeConfig,
    NetlifyUntrustedURLError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import NETLIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.source import NetlifySource

BASE = "https://api.netlify.com/api/v1"


def _response(items: Any, next_url: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.reason = "OK"
    resp._content = json.dumps(items).encode()
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _driver() -> SourceDriver:
    return SourceDriver(NetlifySource(), NetlifySourceConfig(api_token="tok"))


class TestTopLevelPagination:
    def test_paginates_and_checkpoints_after_each_page(self) -> None:
        next_url = f"{BASE}/sites?filter=all&page=2&per_page=100"  # Netlify echoes the query, filter included
        result = _driver().run(
            "sites",
            [
                ScriptedResponse(json=[{"id": "a"}], headers={"Link": f'<{next_url}>; rel="next"'}),
                ScriptedResponse(json=[{"id": "b"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert result.requests[0].param("per_page") == "100"
        # filter=all is load-bearing: without it Netlify returns only sites the token's user
        # personally owns, hiding team sites (and starving every site-scoped fan-out).
        assert result.requests[0].param("filter") == "all"
        # The next-page URL is followed verbatim (params dropped, not re-appended), so the filter
        # rides along to every subsequent page.
        assert result.urls[1] == next_url
        assert result.requests[1].param("filter") == "all"
        # State saved once — after the first page, pointing at the second. The last page has no next
        # link, so nothing is saved for it.
        assert result.saved_states == [NetlifyResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{BASE}/sites?filter=all&page=3&per_page=100"
        result = _driver().run(
            "sites",
            [ScriptedResponse(json=[{"id": "c"}])],
            resume_state=NetlifyResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.rows == [{"id": "c"}]
        assert result.urls == [resume_url]

    def test_empty_first_page_yields_nothing_and_no_checkpoint(self) -> None:
        result = _driver().run("sites", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []

    def test_strips_credential_fields_from_sites(self) -> None:
        # A site object carries account credentials that must never reach the queryable table.
        site = {
            "id": "s1",
            "name": "acme",
            "password": "hunter2",
            "default_hooks_data": {"access_token": "secret-token", "type": "github"},
            "build_settings": {"env": {"STRIPE_KEY": "sk_live_x"}, "cmd": "build"},
        }
        result = _driver().run("sites", [ScriptedResponse(json=[site])])

        assert result.raised is None
        assert result.rows == [
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
    def test_injects_parent_site_id_and_checkpoints_fanout_state(self) -> None:
        result = _driver().run(
            "builds",
            [ScriptedResponse(json=[{"id": "s1"}]), ScriptedResponse(json=[{"id": "b1"}])],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/sites", "/api/v1/sites/s1/builds"]
        # site_id is injected onto each build row (a build carries no site_id of its own).
        assert result.rows == [{"id": "b1", "site_id": "s1"}]
        # The final checkpoint records the parent as fully synced under its resolved child path.
        assert result.saved_states[-1] == NetlifyResumeConfig(
            fanout_state={"completed": ["/sites/s1/builds"], "current": None, "child_state": None}
        )

    def test_resumes_fanout_from_saved_state_skipping_completed_parent(self) -> None:
        result = _driver().run(
            "builds",
            [ScriptedResponse(json=[{"id": "s1"}, {"id": "s2"}]), ScriptedResponse(json=[{"id": "b2"}])],
            resume_state=NetlifyResumeConfig(
                fanout_state={"completed": ["/sites/s1/builds"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        # s1 is already completed, so only s2's builds are fetched on resume (merge dedupes s1).
        assert result.paths == ["/api/v1/sites", "/api/v1/sites/s2/builds"]
        assert result.rows == [{"id": "b2", "site_id": "s2"}]


class TestPageCap:
    def test_capped_paginator_raises_when_parent_exceeds_cap(self) -> None:
        # Hitting the per-parent page cap must fail loudly rather than silently truncate the table.
        paginator = NetlifyCappedHeaderLinkPaginator(max_pages=2, context={"table": "builds"})
        page = [{"id": "x"}]
        paginator.update_state(
            _response(page, next_url=f"{BASE}/sites/s1/builds?page=2"), page
        )  # page 1: under the cap
        with pytest.raises(NetlifyPageCapExceededError):
            # page 2: cap reached with more pages remaining
            paginator.update_state(_response(page, next_url=f"{BASE}/sites/s1/builds?page=3"), page)


class TestFailLoud:
    def test_client_error_raises(self) -> None:
        # A 401/403 is not retryable and must surface as an HTTPError the source maps to a message.
        result = _driver().run("sites", [ScriptedResponse(status=401, json={"code": 401, "message": "Access Denied"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/api/v1/sites"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("rate_limited", 429, False, netlify_module._NETLIFY_UNREACHABLE_ERROR),
            ("netlify_down", 503, False, netlify_module._NETLIFY_UNREACHABLE_ERROR),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("tok") == (expected, message)

        assert network.requests_log[0].path == "/api/v1/sites"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_unexpected_status_reaches_error_tracking(self) -> None:
        with mock.patch.object(netlify_module, "capture_exception") as capture:
            with scripted_network([ScriptedResponse(status=418)]) as network:
                ok, error = validate_credentials("tok")

        assert (ok, error) == (False, netlify_module._NETLIFY_INVALID_TOKEN_ERROR)
        assert error is not None
        assert "418" not in error
        assert network.requests_log[0].path == "/api/v1/sites"
        # The status has to reach error tracking, or a later triage has only the generic message.
        assert "418" in str(capture.call_args.args[0])


class TestNetlifySourceResponse:
    @parameterized.expand(list(NETLIFY_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = NETLIFY_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        response = result.response
        assert response is not None
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
