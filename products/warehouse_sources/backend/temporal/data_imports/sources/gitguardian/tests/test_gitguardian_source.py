from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.gitguardian import (
    GitGuardianResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.source import GitguardianSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_ENDPOINTS = {"secret_incidents", "secret_occurrences", "sources", "honeytokens", "members", "teams"}


class TestGitguardianSourceConfig:
    def test_source_type(self) -> None:
        assert GitguardianSource().source_type == ExternalDataSourceType.GITGUARDIAN

    def test_fields_require_secret_token_and_optional_base_url(self) -> None:
        fields = {f.name: f for f in GitguardianSource().get_source_config.fields}
        api_key, base_url = fields["api_key"], fields["base_url"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(base_url, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert base_url.required is False
        assert base_url.secret is False

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Retargeting base_url must re-require the secret, else the preserved token leaks to a new host.
        assert GitguardianSource().connection_host_fields == ["base_url"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert GitguardianSource.lists_tables_without_credentials is True


class TestGitguardianSchemas:
    def test_incident_endpoints_are_incremental_and_directories_are_full_refresh(self) -> None:
        schemas = {s.name: s for s in GitguardianSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == ALL_ENDPOINTS
        for name in ("secret_incidents", "secret_occurrences"):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"]
        for name in ("sources", "honeytokens", "members", "teams"):
            assert schemas[name].supports_incremental is False

    def test_names_filter(self) -> None:
        schemas = GitguardianSource().get_schemas(MagicMock(), team_id=1, names=["teams"])
        assert [s.name for s in schemas] == ["teams"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.gitguardian.com/v1/incidents/secrets",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://gitguardian.acme.dev/v1/sources"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = GitguardianSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.gitguardian.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error"),
            ("rate_limited", "429 Client Error: Too Many Requests"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = GitguardianSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestValidateCredentials:
    def test_blocks_unsafe_host_before_probing(self) -> None:
        # An internal/private base_url must be rejected without an outbound request being made.
        config = MagicMock(api_key="gg_sat_x", base_url="https://169.254.169.254")
        with (
            patch.object(source_module, "_is_host_safe", return_value=(False, "internal IP blocked")) as host_check,
            patch.object(source_module, "validate_gitguardian_credentials") as probe,
        ):
            valid, error = GitguardianSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert error == "internal IP blocked"
        host_check.assert_called_once()
        probe.assert_not_called()

    def test_rejects_plaintext_base_url_before_probing(self) -> None:
        # A non-HTTPS URL would leak the token; reject it without any outbound request.
        config = MagicMock(api_key="gg_sat_x", base_url="http://gitguardian.acme.dev")
        with patch.object(source_module, "validate_gitguardian_credentials") as probe:
            valid, error = GitguardianSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert error is not None
        probe.assert_not_called()

    def test_source_create_uses_the_scope_free_health_probe(self) -> None:
        config = MagicMock(api_key="gg_sat_x", base_url=None)
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "validate_gitguardian_credentials", return_value=(True, None)) as probe,
        ):
            valid, error = GitguardianSource().validate_credentials(config, team_id=1)
        assert valid is True
        assert error is None
        # Blank base_url resolves to the hosted API URL before probing.
        probe.assert_called_once_with("gg_sat_x", "https://api.gitguardian.com")

    @parameterized.expand(
        [
            ("reachable", None, True),
            ("missing_scope", "missing the `incidents:read` scope", False),
        ]
    )
    def test_per_schema_check_probes_that_endpoint(self, _name: str, reason: str | None, expected: bool) -> None:
        config = MagicMock(api_key="gg_sat_x", base_url=None)
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "check_endpoint_access", return_value=reason) as probe,
        ):
            valid, error = GitguardianSource().validate_credentials(config, team_id=1, schema_name="secret_incidents")
        assert valid is expected
        assert error == reason
        probe.assert_called_once_with("gg_sat_x", "https://api.gitguardian.com", "secret_incidents")


class TestGetEndpointPermissions:
    def test_maps_reachable_and_denied_endpoints(self) -> None:
        config = MagicMock(api_key="gg_sat_x", base_url=None)
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "check_endpoint_access", side_effect=[None, "missing scope"]),
        ):
            permissions = GitguardianSource().get_endpoint_permissions(
                config, team_id=1, endpoints=["secret_incidents", "honeytokens"]
            )
        assert permissions == {"secret_incidents": None, "honeytokens": "missing scope"}


class TestSourceForPipeline:
    def test_plumbs_resolved_base_url_and_incremental_inputs(self) -> None:
        config = MagicMock(api_key="gg_sat_x", base_url="https://gitguardian.acme.dev/")
        inputs = MagicMock(
            schema_name="secret_incidents",
            team_id=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="date",
        )
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "gitguardian_source") as build,
        ):
            result = GitguardianSource().source_for_pipeline(config, MagicMock(), inputs)
        assert result is build.return_value
        kwargs = build.call_args.kwargs
        assert kwargs["base_url"] == "https://gitguardian.acme.dev"
        assert kwargs["endpoint"] == "secret_incidents"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_does_not_pass_watermark_when_not_incremental(self) -> None:
        config = MagicMock(api_key="gg_sat_x", base_url=None)
        inputs = MagicMock(
            schema_name="sources",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field=None,
        )
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "gitguardian_source") as build,
        ):
            GitguardianSource().source_for_pipeline(config, MagicMock(), inputs)
        assert build.call_args.kwargs["db_incremental_field_last_value"] is None


class TestResumableSourceManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = GitguardianSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is GitGuardianResumeConfig


class TestGetDocumentedTables:
    def test_publishes_every_table_with_canonical_descriptions(self) -> None:
        # Guards the canonical_descriptions keys staying aligned with the endpoint names — a drifted
        # key silently drops that table's description from the public docs.
        tables = {t["name"]: t for t in GitguardianSource().get_documented_tables()}
        assert set(tables) == ALL_ENDPOINTS
        for name, table in tables.items():
            assert table["description"], f"{name} lost its canonical description"
        assert "Incremental" in tables["secret_incidents"]["sync_methods"]
        assert tables["sources"]["sync_methods"] == ["Full refresh"]
