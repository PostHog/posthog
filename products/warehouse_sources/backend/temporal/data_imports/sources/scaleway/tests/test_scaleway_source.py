from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scaleway import (
    ScalewaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.source import ScalewaySource


def _config() -> ScalewaySourceConfig:
    return ScalewaySourceConfig(secret_key="scw-secret", organization_id="org-123")


class TestScalewaySource:
    def setup_method(self) -> None:
        self.source = ScalewaySource()
        self.team_id = 123

    @parameterized.expand(
        [
            # (probe status, schema_name, expected valid)
            ("create_ok", 200, None, True),
            ("create_missing_scope_accepted", 403, None, True),
            ("create_bad_token", 401, None, False),
            ("schema_ok", 200, "invoices", True),
            ("schema_missing_scope_rejected", 403, "invoices", False),
            ("schema_bad_token", 401, "invoices", False),
        ]
    )
    def test_validate_credentials(self, _name: str, status: int, schema_name: str | None, expected: bool) -> None:
        with (
            patch.object(source_module, "validate_scaleway_credentials", return_value=status),
            patch.object(source_module, "probe_endpoint", return_value=status),
        ):
            valid, _message = self.source.validate_credentials(_config(), self.team_id, schema_name=schema_name)
        assert valid is expected

    def test_validate_credentials_requires_organization_id(self) -> None:
        valid, message = self.source.validate_credentials(
            ScalewaySourceConfig(secret_key="scw-secret", organization_id=""), self.team_id
        )
        assert valid is False
        assert "Organization ID" in (message or "")

    @parameterized.expand([("forbidden", 403, True), ("reachable", 200, False), ("throttled", 429, False)])
    def test_endpoint_permissions_only_flags_real_denials(self, _name: str, status: int, is_blocked: bool) -> None:
        # Only a genuine 403 marks a table as needing extra scopes; a throttle or 5xx must not block
        # the picker (get_endpoint_permissions must never fail source creation for a transient blip).
        with patch.object(source_module, "probe_endpoint", return_value=status):
            result = self.source.get_endpoint_permissions(_config(), self.team_id, ["invoices"])
        assert (result["invoices"] is not None) is is_blocked

    def _source_inputs(self, schema_name: str) -> SourceInputs:
        return SourceInputs(
            schema_name=schema_name,
            schema_id="schema-1",
            source_id="source-1",
            team_id=self.team_id,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="job-1",
            logger=MagicMock(),
            reset_pipeline=False,
        )
