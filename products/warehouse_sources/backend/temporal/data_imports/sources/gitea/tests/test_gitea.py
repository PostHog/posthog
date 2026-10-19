from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitea import GiteaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea import (
    GiteaResumeConfig,
    _make_webhook_dedupe_transformer,
    _parse_next_url,
    create_repo_webhook,
    delete_repo_webhook,
    get_repo_webhook_info,
    get_rows,
    gitea_source,
    normalize_host,
    update_repo_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.source import GiteaSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea"

BASE_URL = "https://gitea.example.com"
REPO = "owner/repo"


def _driver() -> SourceDriver:
    return SourceDriver(GiteaSource(), GiteaSourceConfig(base_url=BASE_URL, access_token="tok", repository=REPO))


def _make_manager(resume_state: GiteaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://gitea.example.com", "https://gitea.example.com"),
            ("gitea.example.com", "https://gitea.example.com"),
            ("https://gitea.example.com/", "https://gitea.example.com"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "ftp://example.com",
            "https://",
            "http://gitea.example.com",
            # Parser-differential SSRF: urlparse sees example.com, requests connects to the IP.
            "https://169.254.169.254\\@example.com",
            "https://169.254.169.254%40example.com",
            "https://gitea.example.com%5c@169.254.169.254",
            # Credentials in the authority would ship the token to `host`.
            "https://user:pass@gitea.example.com",
            "https://user@gitea.example.com",
        ],
    )
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)


class TestParseNextUrl:
    @pytest.mark.parametrize("header", ["", f'<{BASE_URL}/x?page=1>; rel="last"'])
    def test_no_next_returns_none(self, header):
        assert _parse_next_url(header) is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error_fragment",
        [
            (200, True, None),
            (401, False, "Invalid Gitea access token"),
            (404, False, "not found or not accessible"),
            (302, False, "redirected"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error_fragment: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={"message": "boom"})]) as network:
            is_valid, error = validate_credentials(BASE_URL, "tok", REPO)

        assert is_valid is expected_valid
        if expected_error_fragment:
            assert expected_error_fragment in (error or "")
        assert [request.url for request in network.requests_log] == [f"{BASE_URL}/api/v1/repos/{REPO}"]

    def test_session_carries_token_header_and_never_redirects(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials(BASE_URL, "tok", REPO)

        kwargs = network.session_options[0]
        assert kwargs["headers"]["Authorization"] == "token tok"
        assert kwargs["allow_redirects"] is False
        assert kwargs["redact_values"] == ("tok",)


class TestGetRows:
    def test_paginates_via_link_header_and_saves_state_after_yield(self) -> None:
        page_2_url = f"{BASE_URL}/api/v1/repos/{REPO}/releases?limit=50&page=2"
        result = _driver().run(
            "releases",
            [
                ScriptedResponse(json=[{"id": 1}], headers={"Link": f'<{page_2_url}>; rel="next"'}),
                ScriptedResponse(json=[{"id": 2}]),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}], [{"id": 2}]]
        # State is saved AFTER the batch is yielded, so a crash re-yields it (merge dedupes).
        assert result.saved_states == [GiteaResumeConfig(next_url=page_2_url)]
        assert result.committed_states == [GiteaResumeConfig(next_url=page_2_url)]
        # The last page has no next link — no state saved for it.
        assert result.urls == [f"{BASE_URL}/api/v1/repos/{REPO}/releases?limit=50", page_2_url]

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{BASE_URL}/api/v1/repos/{REPO}/releases?limit=50&page=7"
        result = _driver().run(
            "releases", [ScriptedResponse(json=[])], resume_state=GiteaResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert result.urls == [resume_url]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pull_requests_never_send_since(self, mock_session):
        # /pulls accepts `since` but silently ignores it — sending it would fake an
        # incremental sync that actually re-reads everything.
        mock_session.return_value.get.return_value = _response([])

        list(
            get_rows(
                BASE_URL,
                "tok",
                REPO,
                "pull_requests",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "since=" not in url
        assert "sort=oldest" in url

    @pytest.mark.parametrize(
        "evil_next_url",
        [
            # Plaintext downgrade would send the token header in the clear.
            "http://gitea.example.com/api/v1/repos/owner/repo/issues?page=2",
            # Off-origin host would hand the token to another server (SSRF/exfiltration).
            "https://169.254.169.254/api/v1/repos/owner/repo/issues?page=2",
            "https://gitea.example.com:8443/api/v1/repos/owner/repo/issues?page=2",
        ],
    )
    def test_off_origin_link_header_url_is_rejected(self, evil_next_url: str) -> None:
        result = _driver().run(
            "releases", [ScriptedResponse(json=[{"id": 1}], headers={"Link": f'<{evil_next_url}>; rel="next"'})]
        )

        assert isinstance(result.raised, ValueError)
        assert "not on the configured instance" in str(result.raised)

        # The poisoned URL is never fetched.
        assert len(result.requests) == 1

    def test_off_origin_resume_url_is_rejected(self) -> None:
        result = _driver().run(
            "releases", [], resume_state=GiteaResumeConfig(next_url="https://evil.example.com/api/v1/x")
        )

        assert isinstance(result.raised, ValueError)
        assert "not on the configured instance" in str(result.raised)
        assert result.requests == []

    def test_commits_are_flattened(self) -> None:
        result = _driver().run(
            "commits",
            [
                ScriptedResponse(
                    json=[
                        {
                            "sha": "abc",
                            "created": "2024-01-01T00:00:00Z",
                            "commit": {
                                "message": "fix: thing",
                                "author": {
                                    "name": "Alice",
                                    "email": "alice@example.com",
                                    "date": "2024-01-01T00:00:00Z",
                                },
                                "committer": {
                                    "name": "Bob",
                                    "email": "bob@example.com",
                                    "date": "2024-01-01T00:00:00Z",
                                },
                            },
                            "author": {"id": 7, "login": "alice"},
                            "committer": None,
                        }
                    ]
                )
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        assert row["message"] == "fix: thing"
        assert row["author_name"] == "Alice"
        assert row["author_email"] == "alice@example.com"
        assert row["committer_name"] == "Bob"
        assert row["author_id"] == 7
        assert row["author_login"] == "alice"
        # The commit timestamp survives as the cursor/partition column.
        assert row["created"] == "2024-01-01T00:00:00Z"

    @pytest.mark.parametrize(
        "endpoint, page_1, page_2, headers",
        [
            ("issue_comments", [{"id": 1}, {"id": 2}], [{"id": 3}], {"X-Total-Count": "3"}),
            (
                "workflow_runs",
                {"total_count": 3, "workflow_runs": [{"id": 3}, {"id": 2}]},
                {"total_count": 3, "workflow_runs": [{"id": 1}]},
                {},
            ),
            (
                "workflow_jobs",
                {"total_count": 3, "jobs": [{"id": 1}, {"id": 2}]},
                {"total_count": 3, "jobs": [{"id": 3}]},
                {},
            ),
            ("tags", [{"id": 3}, {"id": 2}], [{"id": 1}], {"X-Total-Count": "3"}),
            ("collaborators", [{"id": 1}, {"id": 2}], [{"id": 3}], {"X-Total-Count": "3"}),
        ],
    )
    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_total_count_pagination_pages_by_number_without_link_header(
        self, endpoint: str, page_1: Any, page_2: Any, headers: dict[str, str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=page_1, headers=headers), ScriptedResponse(json=page_2, headers=headers)],
        )

        assert result.raised is None
        assert sorted(row["id"] for row in result.rows) == [1, 2, 3]
        # The total is covered after page 2, so no third request goes out.
        urls = result.urls
        assert len(urls) == 2
        assert "page=2" in urls[1]
        assert result.saved_states == [GiteaResumeConfig(next_url=urls[1])]

    @pytest.mark.parametrize(
        "endpoint, expected_error",
        [
            ("workflow_runs", "Gitea Actions runs are unavailable"),
            ("workflow_jobs", "Gitea Actions jobs are unavailable"),
        ],
    )
    def test_actions_endpoint_not_found_raises_actions_unavailable(self, endpoint: str, expected_error: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(status=404, json={"message": "Not Found"})])

        assert isinstance(result.raised, ValueError)
        assert expected_error in str(result.raised)


class TestFanOut:
    def test_timeline_fans_out_over_issues_in_one_unpaged_request_each(self) -> None:
        issues_page_2 = f"{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=2"
        result = _driver().run(
            "issue_timeline",
            [
                ScriptedResponse(
                    json=[{"number": 1}, {"number": 2}], headers={"Link": f'<{issues_page_2}>; rel="next"'}
                ),
                ScriptedResponse(json=[{"id": 10}, {"id": 11}], headers={"X-Total-Count": "2"}),
                ScriptedResponse(status=404, json={"message": "Not Found"}),
                ScriptedResponse(json=[{"number": 3}]),
                ScriptedResponse(json=[{"id": 30}]),
            ],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 10, "issue_number": 1},
            {"id": 11, "issue_number": 1},
            {"id": 30, "issue_number": 3},
        ]
        urls = result.urls
        timeline_urls = [url for url in urls if "/timeline" in url]
        assert len(timeline_urls) == 3
        # Gitea drops rows from a timeline page after paging, and its X-Total-Count is the
        # filtered page length, so a paged walk can stop early. Without `page` the endpoint
        # returns the whole timeline in one response.
        assert not any("page=" in url or "limit=" in url for url in timeline_urls)
        # The watermark bounds both the parent issues and each issue's timeline.
        assert all("since=2024-01-02T00%3A00%3A00Z" in url for url in [urls[0], *timeline_urls])
        assert "type=issues" in urls[0]
        # State points at the next parent page once every child of the current one is yielded.
        assert result.saved_states == [GiteaResumeConfig(next_url=issues_page_2)]

    def test_resume_starts_from_saved_parent_page(self) -> None:
        resume_url = f"{BASE_URL}/api/v1/repos/{REPO}/pulls?limit=50&page=4"
        result = _driver().run(
            "reviews",
            [ScriptedResponse(json=[{"number": 9}]), ScriptedResponse(json=[{"id": 90}])],
            resume_state=GiteaResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.items == [[{"id": 90, "pull_request_number": 9}]]
        urls = result.urls
        assert urls[0] == resume_url
        # Gitea drops other users' pending reviews after paging, so reviews are fetched unpaged.
        assert urls[1] == f"{BASE_URL}/api/v1/repos/{REPO}/pulls/9/reviews"


class TestGiteaSourceResponse:
    def test_webhook_enabled_drains_webhook_items_with_dedupe(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)
        sentinel = mock.MagicMock()
        webhook_manager.get_items.return_value = sentinel

        response = gitea_source(
            BASE_URL, "tok", REPO, "issues", mock.MagicMock(), _make_manager(), webhook_source_manager=webhook_manager
        )

        assert response.items() is sentinel
        # Issues declare version_keys, so the drain must collapse a batch to one row per id.
        assert webhook_manager.get_items.call_args.kwargs["table_transformer"] is not None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_webhook_disabled_falls_back_to_poll(self, mock_session):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=False)
        mock_session.return_value.get.return_value = _response([])

        response = gitea_source(
            BASE_URL, "tok", REPO, "issues", mock.MagicMock(), _make_manager(), webhook_source_manager=webhook_manager
        )

        assert list(cast(Iterable[Any], response.items())) == []
        webhook_manager.get_items.assert_not_called()


class TestWebhookDedupeTransformer:
    def _table(self, rows: list[dict[str, Any]]) -> pa.Table:
        return pa.Table.from_pylist(rows)

    def test_keeps_newest_state_per_id(self):
        transform = _make_webhook_dedupe_transformer("id", ["updated_at"])
        table = self._table(
            [
                {"id": 1, "state": "open", "updated_at": "2024-01-01T00:00:00Z"},
                {"id": 2, "state": "open", "updated_at": "2024-01-01T00:00:00Z"},
                {"id": 1, "state": "closed", "updated_at": "2024-01-02T00:00:00Z"},
            ]
        )

        result = transform(table).to_pylist()

        assert result == [
            {"id": 2, "state": "open", "updated_at": "2024-01-01T00:00:00Z"},
            {"id": 1, "state": "closed", "updated_at": "2024-01-02T00:00:00Z"},
        ]

    def test_missing_version_column_leaves_table_unchanged(self):
        transform = _make_webhook_dedupe_transformer("id", ["updated_at"])
        table = self._table([{"id": 1}, {"id": 1}])

        assert transform(table).num_rows == 2


class TestWebhookManagement:
    def test_create_posts_gitea_hook_and_returns_secret(self) -> None:
        with scripted_network([ScriptedResponse(status=201, json={"id": 5})]) as network:
            result = create_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"], "s3cret")

        assert result.success is True
        # Gitea never echoes the secret back — it must flow to the hog function via extra_inputs.
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        request = network.requests_log[0]
        assert request.method == "POST"
        assert request.url == f"{BASE_URL}/api/v1/repos/{REPO}/hooks"
        payload = request.json()
        assert payload["type"] == "gitea"
        assert payload["events"] == ["issues"]
        assert payload["config"] == {"url": "https://ph.example/webhook", "content_type": "json", "secret": "s3cret"}

    @pytest.mark.parametrize("status_code", [403, 404])
    def test_create_permission_error_returns_failed_result(self, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]):
            result = create_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"], "s3cret")

        assert result.success is False
        assert "manually" in (result.error or "")

    def test_delete_matches_hook_by_url(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json=[
                        {"id": 1, "config": {"url": "https://other.example/hook"}},
                        {"id": 2, "config": {"url": "https://ph.example/webhook"}},
                    ]
                ),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = delete_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook")

        assert result.success is True
        assert network.requests_log[1].method == "DELETE"
        assert network.requests_log[1].url == f"{BASE_URL}/api/v1/repos/{REPO}/hooks/2"

    def test_delete_with_no_matching_hook_is_success(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            result = delete_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook")

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_update_events_merges_additively(self) -> None:
        # A user-subscribed event (push) must survive the reconcile PATCH.
        with scripted_network(
            [
                ScriptedResponse(
                    json=[{"id": 2, "config": {"url": "https://ph.example/webhook"}, "events": ["push", "issues"]}]
                ),
                ScriptedResponse(json={}),
            ]
        ) as network:
            result = update_repo_webhook_events(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["pull_request"])

        assert result.success is True
        assert network.requests_log[1].method == "PATCH"
        assert network.requests_log[1].json() == {"events": ["issues", "pull_request", "push"]}

    def test_update_events_skips_write_when_already_covered(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json=[
                        {
                            "id": 2,
                            "config": {"url": "https://ph.example/webhook"},
                            "events": ["issues", "pull_request"],
                        }
                    ]
                )
            ]
        ) as network:
            result = update_repo_webhook_events(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"])

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_webhook_info_found_and_missing(self) -> None:
        hook = {"id": 2, "config": {"url": "https://ph.example/webhook"}, "events": ["issues"], "active": True}
        with scripted_network([ScriptedResponse(json=[hook]), ScriptedResponse(json=[hook])]) as network:
            info = get_repo_webhook_info(BASE_URL, "tok", REPO, "https://ph.example/webhook")
            missing = get_repo_webhook_info(BASE_URL, "tok", REPO, "https://nope.example/webhook")

        assert info.exists is True
        assert info.status == "active"
        assert info.enabled_events == ["issues"]
        assert missing.exists is False
        assert [request.method for request in network.requests_log] == ["GET", "GET"]
