import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tempo import TempoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source import TempoSource


class TestTempoSource:
    def setup_method(self) -> None:
        self.source = TempoSource()
        self.team_id = 123
        self.config = TempoSourceConfig(api_token="tempo-token")

    def test_only_worklogs_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["worklogs"].supports_incremental is True
        assert [f["field"] for f in schemas["worklogs"].incremental_fields] == ["updatedAt"]
        for name, schema in schemas.items():
            if name != "worklogs":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    @parameterized.expand([("at_create", None), ("for_schema", "worklogs")])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source.validate_credentials")
    def test_validate_credentials_delegates_with_token_and_schema(
        self, _name: str, schema_name: str | None, mock_validate: mock.MagicMock
    ) -> None:
        # The status-to-message mapping lives in tempo.validate_credentials; here we only assert the
        # source probes with the configured token/schema and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Tempo API token")
        result = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        mock_validate.assert_called_once_with("tempo-token", endpoint=schema_name)
        assert result == (False, "Invalid Tempo API token")

    def test_validate_credentials_rejects_unknown_schema(self) -> None:
        valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="nope")
        assert valid is False
        assert message is not None and "nope" in message

    @parameterized.expand(
        [
            # Only a real denial marks a missing scope — transient failures must not block the table.
            ("forbidden", 403, "Your Tempo API token is missing the view scope for 'teams'"),
            ("unauthorized", 401, "Invalid Tempo API token"),
            ("reachable", 200, None),
            ("server_error", 500, None),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source.check_access")
    def test_get_endpoint_permissions(
        self, _name: str, status: int, expected_reason: str | None, mock_check: mock.MagicMock
    ) -> None:
        mock_check.return_value = (status, None)
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["teams"])
        assert permissions == {"teams": expected_reason}

    def test_get_endpoint_permissions_unknown_endpoint_is_not_probed(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source.check_access"
        ) as mock_check:
            permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["nope"])
        assert permissions == {"nope": None}
        mock_check.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source.tempo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "worklogs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-01T12:30:45Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "tempo-token"
        assert kwargs["endpoint"] == "worklogs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-03-01T12:30:45Z"
        assert kwargs["incremental_field"] == "updatedAt"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Tempo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
