from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio import FleetioResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.source import FleetioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FleetioSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFleetioSource:
    def setup_method(self) -> None:
        self.source = FleetioSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FLEETIO

    def test_config_fields(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "account_token"}
        # The API key is the secret; the account token is an account identifier, not a password.
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        assert fields["account_token"].required is True
        assert fields["account_token"].secret is False

    def test_connection_host_fields_includes_account_token(self) -> None:
        # Changing the targeted Fleetio account must force the API key to be re-entered.
        assert self.source.connection_host_fields == ["account_token"]

    def test_docs_url_matches_doc_filename(self) -> None:
        assert self.source.get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/fleetio"

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_every_endpoint_with_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            labels = {f["field"] for f in schema.incremental_fields}
            assert {"updated_at", "created_at"} <= labels

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["vehicles"])
        assert [s.name for s in schemas] == ["vehicles"]

    def test_documented_tables_render_from_static_catalog(self) -> None:
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        # Canonical descriptions flow through to the public docs.
        assert tables["vehicles"]["description"]
        assert "Full refresh" in tables["vehicles"]["sync_methods"]
        assert "Incremental" in tables["vehicles"]["sync_methods"]

    @pytest.mark.parametrize("probe_result,expected_valid", [(True, True), (False, False)])
    def test_validate_credentials(self, probe_result: bool, expected_valid: bool, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_fleetio_credentials", lambda api_key, account_token: probe_result)
        config = FleetioSourceConfig(api_key="k", account_token="a")
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://secure.fleetio.com/api/v1/vehicles"),
            ("forbidden", "403 Client Error: Forbidden for url: https://secure.fleetio.com/api/v1/parts"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("timeout", "HTTPSConnectionPool(host='secure.fleetio.com', port=443): Read timed out."),
            ("server_error", "500 Server Error for url: https://secure.fleetio.com/api/v1/vehicles"),
            ("rate_limit", "429 Too Many Requests"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_resumable_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is FleetioResumeConfig

    def test_source_for_pipeline_plumbs_args(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_fleetio_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "fleetio_source", fake_fleetio_source)

        config = FleetioSourceConfig(api_key="my-key", account_token="my-acct")
        manager = MagicMock()
        inputs = MagicMock()
        inputs.schema_name = "vehicles"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = "updated_at"

        result: Any = self.source.source_for_pipeline(config, manager, inputs)

        assert result == "response"
        assert captured["api_key"] == "my-key"
        assert captured["account_token"] == "my-acct"
        assert captured["endpoint"] == "vehicles"
        assert captured["resumable_source_manager"] is manager
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01"
        assert captured["incremental_field"] == "updated_at"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "fleetio_source", lambda **kwargs: captured.update(kwargs))

        config = FleetioSourceConfig(api_key="k", account_token="a")
        inputs = MagicMock()
        inputs.schema_name = "vehicles"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = None

        self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None
