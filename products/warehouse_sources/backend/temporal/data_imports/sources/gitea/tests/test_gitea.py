from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import pyarrow as pa
import requests

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

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea"

BASE_URL = "https://gitea.example.com"
REPO = "owner/repo"


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_error_fragment):
        mock_session.return_value.get.return_value = _response({"message": "boom"}, status_code=status_code)

        is_valid, error = validate_credentials(BASE_URL, "tok", REPO)

        assert is_valid is expected_valid
        if expected_error_fragment:
            assert expected_error_fragment in (error or "")
        url = mock_session.return_value.get.call_args.args[0]
        assert url == f"{BASE_URL}/api/v1/repos/{REPO}"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_carries_token_header_and_never_redirects(self, mock_session):
        mock_session.return_value.get.return_value = _response({})

        validate_credentials(BASE_URL, "tok", REPO)

        kwargs = mock_session.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "token tok"
        assert kwargs["allow_redirects"] is False
        assert kwargs["redact_values"] == ("tok",)


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_link_header_and_saves_state_after_yield(self, mock_session):
        page_2_url = f"{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=2"
        mock_session.return_value.get.side_effect = [
            _response([{"id": 1}], headers={"Link": f'<{page_2_url}>; rel="next"'}),
            _response([{"id": 2}]),
        ]
        manager = _make_manager()

        rows_iter = get_rows(BASE_URL, "tok", REPO, "issues", mock.MagicMock(), manager)
        first_batch = next(rows_iter)

        # State is saved AFTER the batch is yielded, so a crash re-yields it (merge dedupes).
        assert first_batch == [{"id": 1}]
        assert manager.save_state.call_count == 0

        assert next(rows_iter) == [{"id": 2}]
        assert [call.args[0].next_url for call in manager.save_state.call_args_list] == [page_2_url]

        with pytest.raises(StopIteration):
            next(rows_iter)
        # The last page has no next link — no state saved for it.
        assert manager.save_state.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_url(self, mock_session):
        resume_url = f"{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=7"
        mock_session.return_value.get.return_value = _response([])

        list(
            get_rows(
                BASE_URL, "tok", REPO, "issues", mock.MagicMock(), _make_manager(GiteaResumeConfig(next_url=resume_url))
            )
        )

        assert mock_session.return_value.get.call_args.args[0] == resume_url

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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_off_origin_link_header_url_is_rejected(self, mock_session, evil_next_url):
        mock_session.return_value.get.return_value = _response(
            [{"id": 1}], headers={"Link": f'<{evil_next_url}>; rel="next"'}
        )

        with pytest.raises(ValueError, match="not on the configured instance"):
            list(get_rows(BASE_URL, "tok", REPO, "issues", mock.MagicMock(), _make_manager()))

        # The poisoned URL is never fetched.
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_off_origin_resume_url_is_rejected(self, mock_session):
        manager = _make_manager(GiteaResumeConfig(next_url="https://evil.example.com/api/v1/x"))

        with pytest.raises(ValueError, match="not on the configured instance"):
            list(get_rows(BASE_URL, "tok", REPO, "issues", mock.MagicMock(), manager))

        mock_session.return_value.get.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_commits_are_flattened(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            [
                {
                    "sha": "abc",
                    "created": "2024-01-01T00:00:00Z",
                    "commit": {
                        "message": "fix: thing",
                        "author": {"name": "Alice", "email": "alice@example.com", "date": "2024-01-01T00:00:00Z"},
                        "committer": {"name": "Bob", "email": "bob@example.com", "date": "2024-01-01T00:00:00Z"},
                    },
                    "author": {"id": 7, "login": "alice"},
                    "committer": None,
                }
            ]
        )

        batches = list(get_rows(BASE_URL, "tok", REPO, "commits", mock.MagicMock(), _make_manager()))

        row = batches[0][0]
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
        ],
    )
    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_total_count_pagination_pages_by_number_without_link_header(
        self, mock_session, endpoint, page_1, page_2, headers
    ):
        mock_session.return_value.get.side_effect = [
            _response(page_1, headers=headers),
            _response(page_2, headers=headers),
        ]
        manager = _make_manager()

        batches = list(get_rows(BASE_URL, "tok", REPO, endpoint, mock.MagicMock(), manager))

        assert sorted(row["id"] for batch in batches for row in batch) == [1, 2, 3]
        # The total is covered after page 2, so no third request goes out.
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert "page=2" in urls[1]
        assert [call.args[0].next_url for call in manager.save_state.call_args_list] == [urls[1]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_workflow_runs_not_found_raises_actions_unavailable(self, mock_session):
        not_found = _response({"message": "Not Found"}, status_code=404)
        not_found.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=not_found)
        mock_session.return_value.get.return_value = not_found

        with pytest.raises(ValueError, match="Gitea Actions runs are unavailable"):
            list(get_rows(BASE_URL, "tok", REPO, "workflow_runs", mock.MagicMock(), _make_manager()))


class TestFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_timeline_fans_out_over_issues_in_one_unpaged_request_each(self, mock_session):
        issues_page_2 = f"{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=2"
        deleted_issue = _response({"message": "Not Found"}, status_code=404)
        deleted_issue.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=deleted_issue)
        responses = {
            f"/repos/{REPO}/issues?": [
                _response([{"number": 1}, {"number": 2}], headers={"Link": f'<{issues_page_2}>; rel="next"'}),
                _response([{"number": 3}]),
            ],
            f"/repos/{REPO}/issues/1/timeline": [_response([{"id": 10}, {"id": 11}], headers={"X-Total-Count": "2"})],
            f"/repos/{REPO}/issues/2/timeline": [deleted_issue],
            f"/repos/{REPO}/issues/3/timeline": [_response([{"id": 30}])],
        }

        def get(url, timeout):
            return next(responses[key].pop(0) for key in responses if key in url)

        mock_session.return_value.get.side_effect = get
        manager = _make_manager()

        batches = list(
            get_rows(
                BASE_URL,
                "tok",
                REPO,
                "issue_timeline",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert [row for batch in batches for row in batch] == [
            {"id": 10, "issue_number": 1},
            {"id": 11, "issue_number": 1},
            {"id": 30, "issue_number": 3},
        ]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
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
        assert [call.args[0].next_url for call in manager.save_state.call_args_list] == [issues_page_2]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_starts_from_saved_parent_page(self, mock_session):
        resume_url = f"{BASE_URL}/api/v1/repos/{REPO}/pulls?limit=50&page=4"
        mock_session.return_value.get.side_effect = [
            _response([{"number": 9}]),
            _response([{"id": 90}]),
        ]

        batches = list(
            get_rows(
                BASE_URL,
                "tok",
                REPO,
                "reviews",
                mock.MagicMock(),
                _make_manager(GiteaResumeConfig(next_url=resume_url)),
            )
        )

        assert batches == [[{"id": 90, "pull_request_number": 9}]]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_create_posts_gitea_hook_and_returns_secret(self, mock_session):
        mock_session.return_value.post.return_value = _response({"id": 5}, status_code=201)

        result = create_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"], "s3cret")

        assert result.success is True
        # Gitea never echoes the secret back — it must flow to the hog function via extra_inputs.
        assert result.extra_inputs == {"signing_secret": "s3cret"}
        call = mock_session.return_value.post.call_args
        assert call.args[0] == f"{BASE_URL}/api/v1/repos/{REPO}/hooks"
        payload = call.kwargs["json"]
        assert payload["type"] == "gitea"
        assert payload["events"] == ["issues"]
        assert payload["config"] == {"url": "https://ph.example/webhook", "content_type": "json", "secret": "s3cret"}

    @pytest.mark.parametrize("status_code", [403, 404])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_create_permission_error_returns_failed_result(self, mock_session, status_code):
        mock_session.return_value.post.return_value = _response({}, status_code=status_code)

        result = create_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"], "s3cret")

        assert result.success is False
        assert "manually" in (result.error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_delete_matches_hook_by_url(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            [
                {"id": 1, "config": {"url": "https://other.example/hook"}},
                {"id": 2, "config": {"url": "https://ph.example/webhook"}},
            ]
        )
        mock_session.return_value.delete.return_value = _response(None, status_code=204)

        result = delete_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook")

        assert result.success is True
        assert mock_session.return_value.delete.call_args.args[0] == f"{BASE_URL}/api/v1/repos/{REPO}/hooks/2"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_delete_with_no_matching_hook_is_success(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        result = delete_repo_webhook(BASE_URL, "tok", REPO, "https://ph.example/webhook")

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_update_events_merges_additively(self, mock_session):
        # A user-subscribed event (push) must survive the reconcile PATCH.
        mock_session.return_value.get.return_value = _response(
            [{"id": 2, "config": {"url": "https://ph.example/webhook"}, "events": ["push", "issues"]}]
        )
        mock_session.return_value.patch.return_value = _response({}, status_code=200)

        result = update_repo_webhook_events(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["pull_request"])

        assert result.success is True
        assert mock_session.return_value.patch.call_args.kwargs["json"] == {
            "events": ["issues", "pull_request", "push"]
        }

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_update_events_skips_write_when_already_covered(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            [{"id": 2, "config": {"url": "https://ph.example/webhook"}, "events": ["issues", "pull_request"]}]
        )

        result = update_repo_webhook_events(BASE_URL, "tok", REPO, "https://ph.example/webhook", ["issues"])

        assert result.success is True
        mock_session.return_value.patch.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_webhook_info_found_and_missing(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            [{"id": 2, "config": {"url": "https://ph.example/webhook"}, "events": ["issues"], "active": True}]
        )

        info = get_repo_webhook_info(BASE_URL, "tok", REPO, "https://ph.example/webhook")
        assert info.exists is True
        assert info.status == "active"
        assert info.enabled_events == ["issues"]

        missing = get_repo_webhook_info(BASE_URL, "tok", REPO, "https://nope.example/webhook")
        assert missing.exists is False
