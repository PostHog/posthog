from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.platformsh import (
    PlatformShSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.platform_sh import (
    AUTH_FAILED_MESSAGE,
    PlatformShAuthenticationError,
    PlatformShClient,
    PlatformShResumeConfig,
    PlatformShUntrustedURLError,
    platform_sh_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import PLATFORM_SH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.source import PlatformShSource

API = "https://api.platform.sh"


def _token(access_token: str = "bearer-1") -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": access_token, "expires_in": 900, "token_type": "bearer"})


def _envelope(items: list[dict[str, Any]], next_href: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"items": items}
    if next_href:
        body["_links"] = {"next": {"href": next_href}}
    return body


def _driver() -> SourceDriver:
    return SourceDriver(PlatformShSource(), PlatformShSourceConfig(api_token="tok", platform="platform_sh"))


class TestPlatformShClientAuth:
    def test_mid_run_401_refreshes_token_and_retries_once(self) -> None:
        # Access tokens expire after ~15 minutes, so a long sync is guaranteed to hit a 401
        # mid-run; the client must re-exchange and retry instead of failing the job.
        with scripted_network(
            [
                _token("bearer-1"),
                ScriptedResponse(status=401),
                _token("bearer-2"),
                ScriptedResponse(json=_envelope([{"id": "org-1"}])),
            ]
        ) as network:
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            response = client.get(f"{API}/organizations")

        assert response.status_code == 200
        assert [request.path for request in network.requests_log] == [
            "/oauth2/token",
            "/organizations",
            "/oauth2/token",
            "/organizations",
        ]
        assert network.requests_log[-1].headers["authorization"] == "Bearer bearer-2"

    @parameterized.expand([("unauthorized", 401), ("bad_request", 400)])
    def test_rejected_token_exchange_raises_auth_error(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"error": "request_unauthorized"})]):
            client = PlatformShClient("bad-tok", "platform_sh", mock.Mock())
            with pytest.raises(PlatformShAuthenticationError, match=AUTH_FAILED_MESSAGE):
                client.get(f"{API}/organizations")

    def test_refuses_off_host_urls(self) -> None:
        with scripted_network([]):
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            with pytest.raises(PlatformShUntrustedURLError):
                client.validate_url("https://evil.example.com/organizations")
            with pytest.raises(PlatformShUntrustedURLError):
                client.validate_url("http://api.platform.sh/organizations")

    def test_refuses_redirected_token_exchange(self) -> None:
        # requests preserves the POST body on 307/308, so following a redirect would re-send the
        # long-lived API token to whatever host the redirect names.
        with scripted_network(
            [ScriptedResponse(status=307, headers={"Location": "https://evil.example.com/oauth2/token"})]
        ) as network:
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            with pytest.raises(PlatformShUntrustedURLError, match="redirect"):
                client.get(f"{API}/organizations")
        assert [request.path for request in network.requests_log] == ["/oauth2/token"]

    def test_sessions_exclude_secret_bearing_bodies_from_capture(self) -> None:
        # Environment/activity responses carry secrets that `_clean_rows` strips only after HTTP
        # sample capture would have recorded the raw body, so capture must stay off — including on
        # the session rebuilt after each token exchange.
        with scripted_network([_token(), ScriptedResponse(json=_envelope([{"id": "org-1"}]))]) as network:
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            client.get(f"{API}/organizations")
        assert len(network.session_options) >= 2  # __init__ + post-exchange rebuild
        assert all(options["capture"] is False for options in network.session_options)


class TestGetRowsOrganizations:
    def test_follows_relative_next_link_and_checkpoints_after_each_page(self) -> None:
        # `_links.next.href` is a relative HAL link; failing to resolve it against the request URL
        # would silently sync only the first page.
        result = _driver().run(
            "organizations",
            [
                _token(),
                ScriptedResponse(json=_envelope([{"id": "org-1"}], next_href="/organizations?page%5Bafter%5D=org-1")),
                ScriptedResponse(json=_envelope([{"id": "org-2"}])),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "org-1"}], [{"id": "org-2"}]]
        second_url = f"{API}/organizations?page%5Bafter%5D=org-1"
        assert result.urls[-1] == second_url
        # Saved once, after yielding the first page, pointing at the second.
        assert result.saved_states == [PlatformShResumeConfig(next_url=second_url)]

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{API}/organizations?page%5Bafter%5D=org-5"
        result = _driver().run(
            "organizations",
            [_token(), ScriptedResponse(json=_envelope([{"id": "org-6"}]))],
            resume_state=PlatformShResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.items == [[{"id": "org-6"}]]
        assert result.urls[-1] == resume_url

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("organizations", [_token(), ScriptedResponse(json=_envelope([]))])

        assert result.raised is None
        assert result.items == []
        assert result.saved_states == []
        assert result.requests[-1].param("page[size]") == "100"


class TestGetRowsOrgFanOut:
    def test_subscriptions_injects_organization_id_and_checkpoints_org_page(self) -> None:
        # Subscription rows carry no organization_id of their own; without the injected column the
        # table loses its org context.
        result = _driver().run(
            "subscriptions",
            [
                _token(),
                ScriptedResponse(json=_envelope([{"id": "org-1"}])),
                ScriptedResponse(json=_envelope([{"id": "sub-1", "plan": "medium"}])),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "sub-1", "plan": "medium", "organization_id": "org-1"}]]
        assert result.paths[-2:] == ["/organizations", "/organizations/org-1/subscriptions"]
        assert result.saved_states == [PlatformShResumeConfig(next_url=f"{API}/organizations?page%5Bsize%5D=100")]

    def test_environments_fan_out_walks_orgs_then_projects_and_strips_basic_auth(self) -> None:
        result = _driver().run(
            "environments",
            [
                _token(),
                ScriptedResponse(json=_envelope([{"id": "org-1"}])),
                ScriptedResponse(json=_envelope([{"id": "proj-1"}])),
                ScriptedResponse(
                    json=[
                        {
                            "id": "main",
                            "status": "active",
                            "http_access": {"is_enabled": True, "basic_auth": {"admin": "hunter2"}},
                        }
                    ]
                ),
            ],
        )

        # project_id is injected (feeds the composite primary key) and the plaintext
        # basic-auth credential block never reaches the warehouse row.
        assert result.raised is None
        assert result.paths[-3:] == [
            "/organizations",
            "/organizations/org-1/projects",
            "/projects/proj-1/environments",
        ]
        assert result.items == [
            [
                {
                    "id": "main",
                    "status": "active",
                    "http_access": {"is_enabled": True},
                    "project_id": "proj-1",
                }
            ]
        ]


class TestGetRowsActivities:
    def _activity(self, activity_id: str, created_at: str) -> dict[str, Any]:
        return {"id": activity_id, "created_at": created_at, "type": "environment.push"}

    def _run(self, activity_pages: list[ScriptedResponse], **inputs: Any) -> DriveResult:
        return _driver().run(
            "activities",
            [
                _token(),
                ScriptedResponse(json=_envelope([{"id": "org-1"}])),
                ScriptedResponse(json=_envelope([{"id": "proj-1"}])),
                *activity_pages,
            ],
            **inputs,
        )

    def test_pages_backwards_with_starts_at_dedupes_and_terminates(self) -> None:
        # The feed is newest-first and `starts_at` bounds by "created before"; a boundary tie can
        # re-return rows. Without id dedupe + the nothing-new stop the walk would loop forever.
        first_page = [
            self._activity("a3", "2026-07-03T00:00:00+00:00"),
            self._activity("a2", "2026-07-02T00:00:00+00:00"),
        ]
        second_page = [
            self._activity("a2", "2026-07-02T00:00:00+00:00"),
            self._activity("a1", "2026-07-01T00:00:00+00:00"),
        ]
        result = self._run([ScriptedResponse(json=page) for page in [first_page, second_page, second_page]])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a3", "a2", "a1"]
        assert all(row["project_id"] == "proj-1" for row in result.rows)
        activity_requests = [request for request in result.requests if request.path.endswith("/activities")]
        assert activity_requests[0].param("starts_at") is None
        # Second page is bounded by the oldest created_at seen so far.
        assert activity_requests[1].param("starts_at") == "2026-07-02T00:00:00+00:00"

    def test_incremental_cutoff_stops_paging_at_watermark(self) -> None:
        # Without the client-side stop every incremental sync re-walks each project's full history:
        # an API-cost bug and, with pruned activities, a correctness trap.
        first_page = [
            self._activity("a3", "2026-07-03T00:00:00+00:00"),
            self._activity("a2", "2026-07-02T00:00:00+00:00"),
        ]
        result = self._run(
            [ScriptedResponse(json=first_page)],
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value="2026-07-02T12:00:00+00:00",
        )

        # Only the row at/after the watermark is yielded, and no second page is requested even
        # though the first page carried rows (the page crossed the watermark).
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a3"]
        assert len([request for request in result.requests if request.path.endswith("/activities")]) == 1

    def test_drops_log_field(self) -> None:
        # `log` is unbounded raw build output and prone to echoing secrets; it must not land in a
        # queryable warehouse row.
        page = [{**self._activity("a1", "2026-07-01T00:00:00+00:00"), "log": "building...\nsecret=x"}]
        result = self._run([ScriptedResponse(json=page), ScriptedResponse(json=[])])

        assert result.raised is None
        assert "log" not in result.rows[0]


class TestValidateCredentials:
    def test_valid_token(self) -> None:
        with scripted_network([_token(), ScriptedResponse(json=_envelope([{"id": "org-1"}]))]) as network:
            assert validate_credentials("tok", "platform_sh", mock.Mock()) == (True, None)
        assert network.requests_log[-1].path == "/organizations"

    def test_rejected_token(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={})]) as network:
            ok, error = validate_credentials("bad", "platform_sh", mock.Mock())
        assert ok is False
        assert error == "Invalid Platform.sh API token"
        assert [request.path for request in network.requests_log] == ["/oauth2/token"]


class TestPlatformShSourceResponse:
    @parameterized.expand(list(PLATFORM_SH_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = PLATFORM_SH_ENDPOINTS[endpoint]
        manager = PlatformShSource().get_resumable_source_manager(source_inputs(endpoint))
        response = platform_sh_source("tok", "platform_sh", endpoint, mock.Mock(), manager)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [config.partition_key]
