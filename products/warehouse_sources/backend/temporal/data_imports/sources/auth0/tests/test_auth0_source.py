from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.source import Auth0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.auth0 import Auth0SourceConfig

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.auth0.source"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "users",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 7,
        "should_use_incremental_field": True,
        "db_incremental_field_last_value": "2024-01-01T00:00:00.000Z",
        "db_incremental_field_earliest_value": None,
        "incremental_field": "updated_at",
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    return SourceInputs(**{**defaults, **overrides})


class TestAuth0Source:
    def setup_method(self) -> None:
        self.source = Auth0Source()
        self.team_id = 7
        self.config = Auth0SourceConfig(auth0_domain="tenant.us.auth0.com", client_id="cid", client_secret="secret")

    def test_connection_host_fields_pin_the_domain(self) -> None:
        # Without this, an org member could retarget the domain at a server they control and the
        # preserved client secret would be sent there.
        assert self.source.connection_host_fields == ["auth0_domain"]

    def test_table_catalog_is_listed_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("schema_name", [None, "users"])
    def test_validate_credentials_passes_the_config_through(self, schema_name: Optional[str]) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_auth0_credentials", return_value=(True, None)) as mock_validate:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name) == (True, None)

        kwargs = mock_validate.call_args.kwargs
        assert kwargs == {
            "domain": "tenant.us.auth0.com",
            "client_id": "cid",
            "client_secret": "secret",
            "api_version": "v2",
            "schema_name": schema_name,
            "team_id": self.team_id,
        }

    def test_source_for_pipeline_forwards_the_incremental_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        with mock.patch(f"{SOURCE_MODULE}.auth0_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, _inputs())

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "users"
        assert kwargs["api_version"] == "v2"
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 7

    def test_full_refresh_drops_the_watermark(self) -> None:
        inputs = _inputs(should_use_incremental_field=False, schema_name="clients")
        manager = self.source.get_resumable_source_manager(inputs)
        with mock.patch(f"{SOURCE_MODULE}.auth0_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
