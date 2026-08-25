from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh import platform_sh
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.platform_sh import (
    AUTH_FAILED_MESSAGE,
    PlatformShAuthenticationError,
    PlatformShClient,
    PlatformShResumeConfig,
    PlatformShUntrustedURLError,
    get_rows,
    platform_sh_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import PLATFORM_SH_ENDPOINTS

API = "https://api.platform.sh"


def _resp(data: Any, status: int = 200) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    response.json.return_value = data
    return response


def _token_resp(access_token: str = "bearer-1") -> mock.Mock:
    return _resp({"access_token": access_token, "expires_in": 900, "token_type": "bearer"})


def _envelope(items: list[dict[str, Any]], next_href: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"items": items}
    if next_href:
        body["_links"] = {"next": {"href": next_href}}
    return body


def _manager(resume: PlatformShResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _session(get_side_effect: Any, post_side_effect: Any = None) -> mock.Mock:
    session = mock.Mock()
    session.get.side_effect = get_side_effect
    session.post.side_effect = post_side_effect or (lambda *a, **k: _token_resp())
    return session


class TestPlatformShClientAuth:
    def test_exchanges_api_token_before_first_request(self) -> None:
        session = _session([_resp(_envelope([{"id": "org-1"}]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            client.get(f"{API}/organizations")

        post_call = session.post.call_args
        assert post_call.args[0] == "https://auth.api.platform.sh/oauth2/token"
        assert post_call.kwargs["auth"] == ("platform-api-user", "")
        assert post_call.kwargs["data"] == {"grant_type": "api_token", "api_token": "api-tok"}
        # The bearer token, not the raw API token, authenticates the data request.
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer bearer-1"

    def test_upsun_platform_uses_upsun_hosts(self) -> None:
        session = _session([_resp(_envelope([]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            client = PlatformShClient("api-tok", "upsun", mock.Mock())
            client.get(f"{client.api_base}/organizations")

        assert client.api_base == "https://api.upsun.com"
        assert session.post.call_args.args[0] == "https://auth.upsun.com/oauth2/token"

    def test_mid_run_401_refreshes_token_and_retries_once(self) -> None:
        # Access tokens expire after ~15 minutes, so a long sync is guaranteed to hit a 401
        # mid-run; the client must re-exchange and retry instead of failing the job.
        tokens = iter([_token_resp("bearer-1"), _token_resp("bearer-2")])
        session = _session(
            [_resp({}, status=401), _resp(_envelope([{"id": "org-1"}]))],
            post_side_effect=lambda *a, **k: next(tokens),
        )
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            response = client.get(f"{API}/organizations")

        assert response.status_code == 200
        assert session.post.call_count == 2
        assert session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer bearer-2"

    @parameterized.expand([("unauthorized", 401), ("bad_request", 400)])
    def test_rejected_token_exchange_raises_auth_error(self, _name: str, status: int) -> None:
        session = _session([], post_side_effect=lambda *a, **k: _resp({"error": "request_unauthorized"}, status=status))
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            client = PlatformShClient("bad-tok", "platform_sh", mock.Mock())
            with pytest.raises(PlatformShAuthenticationError, match=AUTH_FAILED_MESSAGE):
                client.get(f"{API}/organizations")

    def test_refuses_off_host_urls(self) -> None:
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=mock.Mock()):
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
        with pytest.raises(PlatformShUntrustedURLError):
            client.validate_url("https://evil.example.com/organizations")
        with pytest.raises(PlatformShUntrustedURLError):
            client.validate_url("http://api.platform.sh/organizations")

    def test_refuses_redirected_token_exchange(self) -> None:
        # requests preserves the POST body on 307/308, so following a redirect would re-send the
        # long-lived API token to whatever host the redirect names.
        session = _session([], post_side_effect=lambda *a, **k: _resp({}, status=307))
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            with pytest.raises(PlatformShUntrustedURLError, match="redirect"):
                client.get(f"{API}/organizations")
        assert session.post.call_args.kwargs["allow_redirects"] is False

    def test_sessions_exclude_secret_bearing_bodies_from_capture(self) -> None:
        # Environment/activity responses carry secrets that `_clean_rows` strips only after HTTP
        # sample capture would have recorded the raw body, so capture must stay off — including on
        # the session rebuilt after each token exchange.
        session = _session([_resp(_envelope([{"id": "org-1"}]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session) as factory:
            client = PlatformShClient("api-tok", "platform_sh", mock.Mock())
            client.get(f"{API}/organizations")
        assert factory.call_count >= 2  # __init__ + post-exchange rebuild
        assert all(call.kwargs["capture"] is False for call in factory.call_args_list)


class TestGetRowsOrganizations:
    def test_follows_relative_next_link_and_checkpoints_after_each_page(self) -> None:
        # `_links.next.href` is a relative HAL link; failing to resolve it against the request URL
        # would silently sync only the first page.
        manager = _manager()
        session = _session(
            [
                _resp(_envelope([{"id": "org-1"}], next_href="/organizations?page%5Bafter%5D=org-1")),
                _resp(_envelope([{"id": "org-2"}])),
            ]
        )
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "organizations", mock.Mock(), manager))

        assert batches == [[{"id": "org-1"}], [{"id": "org-2"}]]
        second_url = session.get.call_args_list[1].args[0]
        assert second_url == f"{API}/organizations?page%5Bafter%5D=org-1"
        # Saved once, after yielding the first page, pointing at the second.
        manager.save_state.assert_called_once_with(PlatformShResumeConfig(next_url=second_url))

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{API}/organizations?page%5Bafter%5D=org-5"
        manager = _manager(PlatformShResumeConfig(next_url=resume_url))
        session = _session([_resp(_envelope([{"id": "org-6"}]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "organizations", mock.Mock(), manager))

        assert batches == [[{"id": "org-6"}]]
        assert session.get.call_args_list[0].args[0] == resume_url

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _manager()
        session = _session([_resp(_envelope([]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            assert list(get_rows("tok", "platform_sh", "organizations", mock.Mock(), manager)) == []
        manager.save_state.assert_not_called()


class TestGetRowsOrgFanOut:
    def test_subscriptions_injects_organization_id_and_checkpoints_org_page(self) -> None:
        # Subscription rows carry no organization_id of their own; without the injected column the
        # table loses its org context.
        manager = _manager()

        def get(url: str, **_kwargs: Any) -> mock.Mock:
            if url == f"{API}/organizations?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "org-1"}]))
            if url == f"{API}/organizations/org-1/subscriptions?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "sub-1", "plan": "medium"}]))
            raise AssertionError(f"unexpected url: {url}")

        session = _session(get)
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "subscriptions", mock.Mock(), manager))

        assert batches == [[{"id": "sub-1", "plan": "medium", "organization_id": "org-1"}]]
        manager.save_state.assert_called_once_with(
            PlatformShResumeConfig(next_url=f"{API}/organizations?page%5Bsize%5D=100")
        )

    def test_environments_fan_out_walks_orgs_then_projects_and_strips_basic_auth(self) -> None:
        manager = _manager()

        def get(url: str, **_kwargs: Any) -> mock.Mock:
            if url == f"{API}/organizations?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "org-1"}]))
            if url == f"{API}/organizations/org-1/projects?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "proj-1"}]))
            if url == f"{API}/projects/proj-1/environments":
                return _resp(
                    [
                        {
                            "id": "main",
                            "status": "active",
                            "http_access": {"is_enabled": True, "basic_auth": {"admin": "hunter2"}},
                        }
                    ]
                )
            raise AssertionError(f"unexpected url: {url}")

        session = _session(get)
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "environments", mock.Mock(), manager))

        # project_id is injected (feeds the composite primary key) and the plaintext
        # basic-auth credential block never reaches the warehouse row.
        assert batches == [
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

    def _fan_out_session(self, activity_pages: list[mock.Mock]) -> mock.Mock:
        pages = iter(activity_pages)

        def get(url: str, **_kwargs: Any) -> mock.Mock:
            if url == f"{API}/organizations?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "org-1"}]))
            if url == f"{API}/organizations/org-1/projects?page%5Bsize%5D=100":
                return _resp(_envelope([{"id": "proj-1"}]))
            if url.startswith(f"{API}/projects/proj-1/activities"):
                return next(pages)
            raise AssertionError(f"unexpected url: {url}")

        return _session(get)

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
        session = self._fan_out_session([_resp(first_page), _resp(second_page), _resp(second_page)])

        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "activities", mock.Mock(), _manager()))

        rows = [row for batch in batches for row in batch]
        assert [row["id"] for row in rows] == ["a3", "a2", "a1"]
        assert all(row["project_id"] == "proj-1" for row in rows)

        activity_urls = [c.args[0] for c in session.get.call_args_list if "/activities" in c.args[0]]
        assert "starts_at" not in activity_urls[0]
        # Second page is bounded by the oldest created_at seen so far.
        assert "starts_at=2026-07-02T00%3A00%3A00%2B00%3A00" in activity_urls[1]

    def test_incremental_cutoff_stops_paging_at_watermark(self) -> None:
        # Without the client-side stop every incremental sync re-walks each project's full history:
        # an API-cost bug and, with pruned activities, a correctness trap.
        first_page = [
            self._activity("a3", "2026-07-03T00:00:00+00:00"),
            self._activity("a2", "2026-07-02T00:00:00+00:00"),
        ]
        session = self._fan_out_session([_resp(first_page)])

        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    "tok",
                    "platform_sh",
                    "activities",
                    mock.Mock(),
                    _manager(),
                    should_use_incremental_field=True,
                    incremental_field="created_at",
                    db_incremental_field_last_value="2026-07-02T12:00:00+00:00",
                )
            )

        # Only the row at/after the watermark is yielded, and no second page is requested even
        # though the first page carried rows (the page crossed the watermark).
        rows = [row for batch in batches for row in batch]
        assert [row["id"] for row in rows] == ["a3"]
        activity_urls = [c.args[0] for c in session.get.call_args_list if "/activities" in c.args[0]]
        assert len(activity_urls) == 1

    def test_no_watermark_keeps_walking_until_exhausted(self) -> None:
        first_page = [self._activity("a2", "2026-07-02T00:00:00+00:00")]
        second_page = [self._activity("a1", "2026-07-01T00:00:00+00:00")]
        session = self._fan_out_session([_resp(first_page), _resp(second_page), _resp([])])

        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "activities", mock.Mock(), _manager()))

        rows = [row for batch in batches for row in batch]
        assert [row["id"] for row in rows] == ["a2", "a1"]

    def test_drops_log_field(self) -> None:
        # `log` is unbounded raw build output and prone to echoing secrets; it must not land in a
        # queryable warehouse row.
        page = [{**self._activity("a1", "2026-07-01T00:00:00+00:00"), "log": "building...\nsecret=x"}]
        session = self._fan_out_session([_resp(page), _resp([])])

        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "platform_sh", "activities", mock.Mock(), _manager()))

        assert "log" not in batches[0][0]


class TestValidateCredentials:
    def test_valid_token(self) -> None:
        session = _session([_resp(_envelope([{"id": "org-1"}]))])
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            assert validate_credentials("tok", "platform_sh", mock.Mock()) == (True, None)

    def test_rejected_token(self) -> None:
        session = _session([], post_side_effect=lambda *a, **k: _resp({}, status=401))
        with mock.patch.object(platform_sh, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("bad", "platform_sh", mock.Mock())
        assert ok is False
        assert error == "Invalid Platform.sh API token"


class TestPlatformShSourceResponse:
    @parameterized.expand(list(PLATFORM_SH_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = PLATFORM_SH_ENDPOINTS[endpoint]
        response = platform_sh_source("tok", "platform_sh", endpoint, mock.Mock(), _manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [config.partition_key]
