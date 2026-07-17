import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.naming import (
    resolve_schema_repo_endpoint,
    split_schema_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_GITHUB_INTEGRATION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GitHubIntegration"
)


def _pat_config(repository: str | None = None, repositories: list[str] | None = None) -> GithubSourceConfig:
    return GithubSourceConfig(
        auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
        repository=repository,
        repositories=repositories,
    )


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @mock.patch(_GITHUB_INTEGRATION_PATH)
    @mock.patch.object(GithubSource, "get_oauth_integration")
    def test_get_oauth_accounts_maps_repositories(self, mock_get_oauth, mock_github_integration):
        mock_get_oauth.return_value = mock.MagicMock()
        mock_github_integration.return_value.list_cached_repositories.return_value = (
            [{"full_name": "PostHog/posthog"}, {"full_name": "PostHog/code"}],
            False,
        )

        accounts = self.source.get_oauth_accounts(1, self.team_id)

        assert [a.value for a in accounts] == ["PostHog/posthog", "PostHog/code"]
        assert [a.display_name for a in accounts] == ["PostHog/posthog", "PostHog/code"]
        mock_get_oauth.assert_called_once_with(1, self.team_id)

    @mock.patch(_GITHUB_INTEGRATION_PATH)
    @mock.patch.object(GithubSource, "get_oauth_integration")
    def test_get_oauth_accounts_pushes_search_down(self, mock_get_oauth, mock_github_integration):
        mock_get_oauth.return_value = mock.MagicMock()
        list_repos = mock_github_integration.return_value.list_cached_repositories
        list_repos.return_value = ([], False)

        self.source.get_oauth_accounts(1, self.team_id, search="posthog")

        list_repos.assert_called_once_with(search="posthog", limit=100, offset=0)

    @mock.patch(_GITHUB_INTEGRATION_PATH)
    @mock.patch.object(GithubSource, "get_oauth_integration")
    def test_get_oauth_accounts_skips_repos_without_full_name(self, mock_get_oauth, mock_github_integration):
        mock_get_oauth.return_value = mock.MagicMock()
        mock_github_integration.return_value.list_cached_repositories.return_value = (
            [{"full_name": "PostHog/posthog"}, {"full_name": ""}, {"id": 1}],
            False,
        )

        accounts = self.source.get_oauth_accounts(1, self.team_id)

        assert [a.value for a in accounts] == ["PostHog/posthog"]

    @mock.patch.object(GithubSource, "get_oauth_integration")
    def test_get_oauth_accounts_missing_integration_raises(self, mock_get_oauth):
        mock_get_oauth.side_effect = ValueError("Integration not found")

        with pytest.raises(IntegrationAccountListingError):
            self.source.get_oauth_accounts(999, self.team_id)

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "404 Client Error",
            "Bad credentials",
            "Missing GitHub integration ID",
            "Missing personal access token",
            "GitHub access token not found",
            "Integration not found",
            "Missing integration ID",
            "This installation has been suspended",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_suspended_installation_token_refresh_is_non_retryable(self):
        # The raw GitHubIntegrationError raised by refresh_access_token on a suspended installation.
        error_message = (
            'Failed to refresh installation token: {"message":"This installation has been suspended",'
            '"documentation_url":"https://docs.github.com/rest/reference/apps#create-an-installation-access-token-for-an-app",'
            '"status":"403"}'
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert "This installation has been suspended" in non_retryable_errors
        assert "This installation has been suspended" in error_message

    @pytest.mark.parametrize(
        "selection,github_integration_id,personal_access_token,expected_error",
        [
            # OAuth selected but no account connected (or integration deleted) — the message
            # raised here must match a get_non_retryable_errors key so the schema stops retrying.
            ("oauth", None, "", "Missing GitHub integration ID"),
            ("pat", None, "", "Missing personal access token"),
        ],
    )
    def test_get_access_token_error_is_non_retryable(
        self, selection, github_integration_id, personal_access_token, expected_error
    ):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=github_integration_id,
                selection=selection,
                personal_access_token=personal_access_token,
            ),
            repository="owner/repo",
        )

        with pytest.raises(ValueError, match=expected_error):
            self.source._get_access_token(config, self.team_id)

        assert expected_error in self.source.get_non_retryable_errors()

    def test_endpoint_permissions_surface_credential_errors_per_table(self):
        # The schema-picker caller swallows exceptions from get_endpoint_permissions and falls back
        # to "all reachable", so a raising token fetch must be mapped to a per-table reason here or
        # a broken integration shows the org tables as available and fails only at sync time.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="oauth", personal_access_token=""),
            repository="acme/widgets",
        )

        result = self.source.get_endpoint_permissions(config, self.team_id, ["teams", "team_members", "issues"])

        assert result["issues"] is None
        assert result["teams"] == "No GitHub account is connected. Please reconnect your GitHub account."
        assert result["team_members"] == result["teams"]

    @pytest.mark.parametrize("endpoint", ["teams", "team_members"])
    def test_org_schemas_are_full_refresh_only_and_off_by_default(self, endpoint):
        # teams / team_members expose no timestamps, so they must never advertise incremental,
        # append, or webhook sync; otherwise the picker would offer a mode that syncs nothing.
        # And they need an org grant repo-scoped connections lack, so they must start
        # deselected; default-on would make a fresh source's first sync fail with 403/404.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
        )
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.supports_webhooks is False
        assert schema.webhook_only is False
        assert schema.should_sync_default is False

    def test_existing_workflow_schemas_stay_webhook_capable(self):
        # Guard that adding the org endpoints didn't disturb the webhook-capable schemas.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
        )
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        assert schemas["workflow_runs"].supports_webhooks is True
        assert schemas["workflow_jobs"].supports_webhooks is True
        assert all(s.should_sync_default for s in schemas.values() if s.name not in ("teams", "team_members"))

    def test_reviews_schema_is_webhook_only_and_default_on(self):
        # reviews does no poll backfill (zero lookback floor), so it must be offered webhook-only;
        # advertising a poll mode would sync an empty table forever. It needs only the repo grant
        # validated at create, unlike the org tables, so it stays selected by default. If the
        # webhook map entry or the zero floor regressed, these flags would flip and the picker
        # would offer a broken mode.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
        )
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        reviews = schemas["reviews"]
        assert reviews.supports_webhooks is True
        assert reviews.webhook_only is True
        assert reviews.supports_incremental is False
        assert reviews.supports_append is False
        assert reviews.should_sync_default is True
        assert [f["field"] for f in reviews.incremental_fields] == ["submitted_at"]

    def test_get_access_token_returns_pat(self):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=None, selection="pat", personal_access_token="github_pat_123"
            ),
            repository="owner/repo",
        )

        assert self.source._get_access_token(config, self.team_id) == "github_pat_123"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GitHubIntegration")
    def test_get_access_token_via_oauth(self, mock_github_integration):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=42, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        integration = mock.MagicMock()
        integration.access_token = "gho_token"
        with mock.patch.object(self.source, "get_oauth_integration", return_value=integration):
            mock_github_integration.return_value.access_token_expired.return_value = False
            assert self.source._get_access_token(config, self.team_id) == "gho_token"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GitHubIntegration")
    def test_get_access_token_missing_oauth_token_is_non_retryable(self, mock_github_integration):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=42, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        integration = mock.MagicMock()
        integration.access_token = None
        with mock.patch.object(self.source, "get_oauth_integration", return_value=integration):
            mock_github_integration.return_value.access_token_expired.return_value = False
            with pytest.raises(ValueError, match="GitHub access token not found"):
                self.source._get_access_token(config, self.team_id)

        assert "GitHub access token not found" in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "selection,expected_message",
        [
            ("oauth", "No GitHub account is connected. Please reconnect your GitHub account."),
            ("pat", "GitHub personal access token is not configured. Please update the source configuration."),
        ],
    )
    def test_validate_credentials_maps_config_errors_to_friendly_message(self, selection, expected_message):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=None, selection=selection, personal_access_token=""
            ),
            repository="owner/repo",
        )

        valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        # The wizard surfaces this string directly, so it must be the friendly copy, not the
        # internal "Missing ..." developer string raised by `_get_access_token`.
        assert message == expected_message

    @pytest.mark.parametrize(
        "repository,repositories,expected",
        [
            # Legacy single-repo sources fall back to `repository` — breaking this breaks
            # sync routing for every pre-multi-repo source.
            ("PostHog/posthog", None, ["posthog/posthog"]),
            (None, ["PostHog/posthog", "posthog/posthog", " Other/Repo "], ["posthog/posthog", "other/repo"]),
            # A non-empty `repositories` is the authoritative set; `repository` only marks bare naming.
            ("posthog/posthog", ["a/b"], ["a/b"]),
        ],
    )
    def test_effective_repositories(self, repository, repositories, expected):
        assert GithubSource.effective_repositories(_pat_config(repository, repositories)) == expected

    def test_effective_repositories_raises_without_any_repo(self):
        with pytest.raises(ValueError, match="No repositories configured"):
            GithubSource.effective_repositories(_pat_config(None, None))
        assert "No repositories configured" in self.source.get_non_retryable_errors()

    def test_effective_repositories_rejects_storage_collision(self):
        # `acme/repo.name` and `acme/repo__name` collapse to the same table/folder identifier; the
        # source must reject the pair rather than silently mix two repos' data into one table.
        with pytest.raises(ValueError, match="resolve to the same warehouse table"):
            GithubSource.effective_repositories(_pat_config(None, ["acme/repo.name", "acme/repo__name"]))
        assert "resolve to the same warehouse table" in self.source.get_non_retryable_errors()

    def test_effective_repositories_rejects_over_the_maximum(self):
        too_many = [f"acme/repo{i}" for i in range(GithubSource.MAX_REPOSITORIES + 1)]
        with pytest.raises(ValueError, match="Too many repositories configured"):
            GithubSource.effective_repositories(_pat_config(None, too_many))
        assert "Too many repositories configured" in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("issues", (None, "issues")),
            ("posthog/posthog.issues", ("posthog/posthog", "issues")),
            # Repo names can contain dots — a naive rpartition('.') would split `next.js` wrong.
            ("posthog/next.js.issues", ("posthog/next.js", "issues")),
            ("posthog/next.js.pull_requests", ("posthog/next.js", "pull_requests")),
            # Unrecognized suffixes stay whole so unknown rows don't get misrouted.
            ("posthog/posthog.not_an_endpoint", (None, "posthog/posthog.not_an_endpoint")),
        ],
    )
    def test_split_schema_name(self, name, expected):
        assert split_schema_name(name) == expected

    def test_resolve_schema_repo_endpoint_metadata_wins_over_name(self):
        # A repo rename edge or hand-edited row name must never override the persisted location.
        config = _pat_config(repository="legacy/repo")
        assert resolve_schema_repo_endpoint(
            {"source_repository": "Real/Repo", "source_endpoint": "issues"},
            "misleading/name.pull_requests",
            config,
        ) == ("real/repo", "issues")
        assert resolve_schema_repo_endpoint(None, "other/repo.issues", config) == ("other/repo", "issues")
        assert resolve_schema_repo_endpoint(None, "issues", config) == ("legacy/repo", "issues")

    def test_resolve_schema_repo_endpoint_bare_without_config_repo_raises_non_retryable(self):
        with pytest.raises(ValueError, match="No repositories configured"):
            resolve_schema_repo_endpoint(None, "issues", _pat_config(None, ["a/b"]))

    def test_get_schemas_legacy_single_repo_stays_bare(self):
        # Pre-multi-repo sources must keep their exact schema names or existing rows,
        # tables, and saved queries all detach.
        schemas = self.source.get_schemas(_pat_config(repository="acme/widgets"), self.team_id)
        assert [s.name for s in schemas] == list(ENDPOINTS)
        assert all(s.schema_metadata is None for s in schemas)

    def test_get_schemas_legacy_source_with_added_repo_mixes_bare_and_qualified(self):
        config = _pat_config(repository="acme/widgets", repositories=["acme/widgets", "acme/other"])
        schemas = self.source.get_schemas(config, self.team_id)

        names = [s.name for s in schemas]
        assert names == [*ENDPOINTS, *[f"acme/other.{endpoint}" for endpoint in ENDPOINTS]]
        qualified = {s.name: s for s in schemas if s.schema_metadata}
        assert set(qualified) == {f"acme/other.{endpoint}" for endpoint in ENDPOINTS}
        assert qualified["acme/other.issues"].schema_metadata == {
            "source_repository": "acme/other",
            "source_endpoint": "issues",
        }
        assert qualified["acme/other.issues"].label == "acme/other · issues"

    def test_get_schemas_new_format_source_is_fully_qualified_even_with_one_repo(self):
        # New sources always qualify so adding repo #2 later never renames anything.
        schemas = self.source.get_schemas(_pat_config(repositories=["acme/widgets"]), self.team_id)
        assert [s.name for s in schemas] == [f"acme/widgets.{endpoint}" for endpoint in ENDPOINTS]
        assert all(s.schema_metadata for s in schemas)

    @pytest.mark.parametrize(
        "schema_name,expected_key",
        [
            ("workflow_runs", "workflow_run"),
            ("workflow_jobs", "workflow_job"),
            ("reviews", "pull_request_review"),
            # Qualified rows get repo-qualified keys — two repos' workflow_runs would otherwise
            # collide on one "workflow_run" key and route all events to a single schema.
            ("acme/Widgets.workflow_runs", "acme/widgets.workflow_run"),
            ("acme/other.reviews", "acme/other.pull_request_review"),
        ],
    )
    def test_webhook_mapping_key(self, schema_name, expected_key):
        assert self.source.webhook_mapping_key(schema_name) == expected_key

    def test_get_desired_webhook_events_handles_qualified_names_and_dedupes(self):
        config = _pat_config(repositories=["a/b", "c/d"])
        events = self.source.get_desired_webhook_events(
            config, ["a/b.workflow_runs", "c/d.workflow_runs", "a/b.reviews", "a/b.issues"]
        )
        assert events == ["workflow_run", "pull_request_review"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.github.source.validate_github_credentials"
    )
    def test_validate_credentials_aggregates_per_repo_failures(self, mock_validate):
        mock_validate.side_effect = [
            (True, None),
            (False, "Repository 'a/missing' not found or not accessible"),
        ]

        valid, message = self.source.validate_credentials(_pat_config(repositories=["a/ok", "a/missing"]), self.team_id)

        assert valid is False
        assert message is not None and "a/missing" in message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.github.source.validate_github_credentials"
    )
    def test_validate_credentials_short_circuits_on_bad_token(self, mock_validate):
        # A 401 is token-level; probing the remaining repos would produce N identical failures.
        mock_validate.side_effect = [(False, "Invalid personal access token")]

        valid, message = self.source.validate_credentials(_pat_config(repositories=["a/b", "c/d", "e/f"]), self.team_id)

        assert valid is False
        assert message == "Invalid personal access token"
        assert mock_validate.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.github_source")
    def test_source_for_pipeline_resolves_repo_from_metadata(self, mock_github_source):
        config = _pat_config(repository="legacy/repo", repositories=["legacy/repo", "acme/other"])
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "acme/other.issues"
        inputs.schema_metadata = {"source_repository": "acme/other", "source_endpoint": "issues"}
        inputs.s3_folder_name = "acme_other_issues"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        kwargs = mock_github_source.call_args.kwargs
        assert kwargs["repository"] == "acme/other"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["response_name"] == "acme_other_issues"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.github_source")
    def test_source_for_pipeline_bare_row_falls_back_to_legacy_repo(self, mock_github_source):
        config = _pat_config(repository="legacy/repo", repositories=["legacy/repo", "acme/other"])
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "issues"
        inputs.schema_metadata = None
        inputs.s3_folder_name = "issues"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        kwargs = mock_github_source.call_args.kwargs
        assert kwargs["repository"] == "legacy/repo"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["response_name"] == "issues"

    @pytest.mark.parametrize(
        "pin,expected",
        [
            # An existing source pinned to the legacy version keeps syncing on it — the default flip
            # must never silently move a customer to the new version.
            ("2022-11-28", "2022-11-28"),
            ("2026-03-10", "2026-03-10"),
            # An unpinned source resolves to the current default — new sources land here. Every
            # pre-existing row was pinned to the legacy version by the versioning-framework backfill
            # (migration 0075), and creation stamps the pin since, so the flip only reaches new ones.
            (None, "2026-03-10"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.github_source")
    def test_source_for_pipeline_threads_resolved_api_version(self, mock_github_source, pin, expected):
        config = _pat_config(repository="legacy/repo", repositories=["legacy/repo"])
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "issues"
        inputs.schema_metadata = None
        inputs.s3_folder_name = "issues"
        inputs.should_use_incremental_field = False
        inputs.api_version = pin

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_github_source.call_args.kwargs["api_version"] == expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.ensure_repo_webhook")
    def test_create_webhook_shares_one_secret_across_repos(self, mock_ensure):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult

        mock_ensure.return_value = WebhookCreationResult(success=True, extra_inputs={"signing_secret": "ignored"})
        config = _pat_config(repositories=["a/b", "c/d"])

        result = self.source.create_webhook(config, "https://hooks/x", self.team_id)

        assert result.success is True
        secrets_used = {call.kwargs["secret"] for call in mock_ensure.call_args_list}
        # One hog function has one signing_secret input, so every repo's hook must share it.
        assert len(mock_ensure.call_args_list) == 2
        assert len(secrets_used) == 1
        assert result.extra_inputs == {"signing_secret": secrets_used.pop()}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.ensure_repo_webhook")
    def test_create_webhook_partial_failure_keeps_secret_and_reports_repos(self, mock_ensure):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult

        mock_ensure.side_effect = [
            WebhookCreationResult(success=True, extra_inputs={"signing_secret": "x"}),
            WebhookCreationResult(success=False, error="boom"),
        ]
        config = _pat_config(repositories=["a/b", "c/d"])

        result = self.source.create_webhook(config, "https://hooks/x", self.team_id)

        assert result.success is False
        assert result.error is not None and "c/d: boom" in result.error
        # The repo that did get a hook verifies against this secret, so it must still persist.
        assert result.extra_inputs.get("signing_secret")
