from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LaceworkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.lacework import LaceworkResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.settings import (
    ENDPOINTS,
    LACEWORK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source import LaceworkSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source"


class TestLaceworkSource:
    def setup_method(self) -> None:
        self.source = LaceworkSource()
        self.config = LaceworkSourceConfig(account_name="mycompany", key_id="KEY_ID", secret_key="secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LACEWORK

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert list(fields.keys()) == ["account_name", "key_id", "secret_key"]
        assert all(f.required for f in fields.values())
        assert fields["secret_key"].secret is True
        assert fields["account_name"].secret is False

    def test_account_name_is_a_connection_host_field(self) -> None:
        # Retargeting the account (and therefore the host the secret is sent to) must force the
        # editor to re-enter credentials.
        assert self.source.connection_host_fields == ["account_name"]

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_get_schemas_flags_match_endpoint_settings(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        endpoint_config = LACEWORK_ENDPOINTS[endpoint]
        assert schema.supports_incremental == endpoint_config.supports_incremental
        assert schema.supports_append == endpoint_config.supports_append
        assert [f["field"] for f in schema.incremental_fields] == [
            f["field"] for f in endpoint_config.incremental_fields
        ]

    def test_only_alerts_supports_merge_sync(self) -> None:
        # Only alerts has a unique row id (alertId); merge sync on any other endpoint would
        # multi-match rows and corrupt the table.
        incremental = [s.name for s in self.source.get_schemas(self.config, team_id=1) if s.supports_incremental]
        assert incremental == ["alerts"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "audit_logs"])
        assert {s.name for s in schemas} == {"alerts", "audit_logs"}

    @parameterized.expand([(True, None), (False, "Invalid Lacework API key ID or secret key")])
    def test_validate_credentials_delegates_to_transport(self, ok: bool, message: str | None) -> None:
        with patch(f"{_SOURCE_MODULE}.validate_lacework_credentials", return_value=(ok, message)) as mock_validate:
            assert self.source.validate_credentials(self.config, team_id=1) == (ok, message)
        mock_validate.assert_called_once_with("mycompany", "KEY_ID", "secret")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LaceworkResumeConfig

    @parameterized.expand([(True,), (False,)])
    def test_source_for_pipeline_plumbs_inputs(self, should_use_incremental_field: bool) -> None:
        inputs = MagicMock()
        inputs.schema_name = "alerts"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-06-15T06:00:00Z"
        manager = MagicMock()

        with patch(f"{_SOURCE_MODULE}.lacework_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["account_name"] == "mycompany"
        assert kwargs["key_id"] == "KEY_ID"
        assert kwargs["secret_key"] == "secret"
        assert kwargs["endpoint"] == "alerts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        expected_value = "2026-06-15T06:00:00Z" if should_use_incremental_field else None
        assert kwargs["db_incremental_field_last_value"] == expected_value

    @parameterized.expand(
        [
            ("401 Client Error",),
            ("403 Client Error",),
            ("Invalid Lacework account name",),
        ]
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
