from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.terraformcloud import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source import TerraformCloudSource


def _config(api_token: str = "test-token", organization: str = "acme") -> TerraformCloudSourceConfig:
    return TerraformCloudSourceConfig.from_dict({"api_token": api_token, "organization": organization})


def _inputs(schema_name: str, should_use_incremental_field: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestTerraformCloudSource:
    def test_get_schemas_filters_by_name(self) -> None:
        schemas = TerraformCloudSource().get_schemas(_config(), team_id=1, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]

    @parameterized.expand(
        [
            ("bad org/../path", False),
            ("has space", False),
            ("", False),
        ]
    )
    def test_validate_credentials_rejects_invalid_org_names_without_network(self, organization: str, _: bool) -> None:
        # The org name lands in a URL path; a malformed value must be rejected before any request.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials"
        ) as probe:
            ok, message = TerraformCloudSource().validate_credentials(_config(organization=organization), team_id=1)
        assert ok is False
        assert message is not None
        probe.assert_not_called()

    def test_validate_credentials_delegates_probe(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials",
            return_value=(True, None),
        ) as probe:
            assert TerraformCloudSource().validate_credentials(_config(), team_id=1) == (True, None)
        probe.assert_called_once_with("test-token", "acme")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://app.terraform.io/api/v2/workspaces/ws-1/runs",),
            ("403 Client Error: Forbidden for url: https://app.terraform.io/api/v2/organizations/acme/teams",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked token must permanently fail the sync rather than retry forever; the matcher
        # keys on the stable status text + host, so real HTTPError strings match.
        errors = TerraformCloudSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())

    @parameterized.expand([(True, "2026-01-01T00:00:00Z"), (False, None)])
    def test_source_for_pipeline_plumbs_arguments(self, should_use_incremental: bool, expected_last_value: Any) -> None:
        sentinel = object()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.terraform_cloud_source",
            return_value=sentinel,
        ) as mock_source:
            inputs = _inputs("runs", should_use_incremental_field=should_use_incremental)
            result = TerraformCloudSource().source_for_pipeline(_config(organization=" acme "), manager, inputs)

        assert result is sentinel
        mock_source.assert_called_once_with(
            api_token="test-token",
            organization="acme",  # stripped so a pasted name with whitespace doesn't 404 every request
            endpoint="runs",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=expected_last_value,
        )
