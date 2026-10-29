from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitguardian import (
    GitguardianSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.source import GitguardianSource


class TestGitguardianSourceConfig:
    def test_base_url_is_a_connection_host_field(self) -> None:
        # Retargeting base_url must re-require the secret, else the preserved token leaks to a new host.
        assert GitguardianSource().connection_host_fields == ["base_url"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert GitguardianSource.lists_tables_without_credentials is True


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
        result = SourceDriver(
            GitguardianSource(),
            GitguardianSourceConfig(api_key="gg_sat_x", base_url="https://gitguardian.acme.dev/"),
        ).run(
            "secret_incidents",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="date",
        )
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "secret_incidents"
        assert result.requests[0].origin == "https://gitguardian.acme.dev"
        assert result.requests[0].path == "/v1/incidents/secrets"
        assert result.requests[0].param("date_after") == "2025-12-25T00:00:00Z"

    def test_does_not_pass_watermark_when_not_incremental(self) -> None:
        result = SourceDriver(
            GitguardianSource(),
            GitguardianSourceConfig(api_key="gg_sat_x", base_url=None),
        ).run(
            "sources",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        assert result.raised is None
        assert result.requests[0].param("date_after") is None
