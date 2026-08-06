from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea import (
    GiteaResumeConfig,
    _flatten_commit,
    _make_webhook_dedupe_transformer,
    _parse_next_url,
    create_repo_webhook,
    delete_repo_webhook,
    get_repo_webhook_info,
    get_rows,
    gitea_source,
    hostname_of,
    normalize_host,
    update_repo_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.settings import ENDPOINTS, GITEA_ENDPOINTS

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

    def test_hostname_of(self):
        assert hostname_of("https://gitea.example.com/") == "gitea.example.com"


class TestParseNextUrl:
    def test_parses_next_rel_among_others(self):
        header = (
            f'<{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=2>; rel="next",'
            f'<{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=9>; rel="last"'
        )
        assert _parse_next_url(header) == f"{BASE_URL}/api/v1/repos/{REPO}/issues?limit=50&page=2"

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
    def test_incremental_issues_pass_since_and_static_params(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        list(
            get_rows(
                BASE_URL,
                "tok",
                REPO,
                "issues",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "since=2024-01-02T03%3A04%3A05Z" in url
        # type=issues keeps pull requests out of the issues table.
        assert "type=issues" in url
        assert "state=all" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_omits_since(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        list(get_rows(BASE_URL, "tok", REPO, "issues", mock.MagicMock(), _make_manager()))

        assert "since=" not in mock_session.return_value.get.call_args.args[0]

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


class TestFlattenCommit:
    def test_missing_nested_objects_do_not_crash(self):
        assert _flatten_commit({"sha": "abc"}) == {"sha": "abc"}


class TestGiteaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = gitea_source(BASE_URL, "tok", REPO, endpoint, mock.MagicMock(), _make_manager())

        config = GITEA_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_commits_key_on_sha(self):
        response = gitea_source(BASE_URL, "tok", REPO, "commits", mock.MagicMock(), _make_manager())
        assert response.primary_keys == ["sha"]

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

    def test_tie_keeps_later_arriving_row(self):
        transform = _make_webhook_dedupe_transformer("id", ["updated_at"])
        table = self._table(
            [
                {"id": 1, "state": "open", "updated_at": "2024-01-01T00:00:00Z"},
                {"id": 1, "state": "closed", "updated_at": "2024-01-01T00:00:00Z"},
            ]
        )

        assert transform(table).to_pylist() == [{"id": 1, "state": "closed", "updated_at": "2024-01-01T00:00:00Z"}]

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
