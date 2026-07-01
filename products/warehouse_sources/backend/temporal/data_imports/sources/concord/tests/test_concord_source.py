from typing import cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.concord import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.concord import ConcordResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.source import ConcordSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConcordSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestConcordSourceClass:
    def setup_method(self):
        self.source = ConcordSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CONCORD

    def test_source_config_fields(self):
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_key", "environment", "organization_id"}
        api_key_field = cast(SourceFieldInputConfig, fields["api_key"])
        assert api_key_field.required is True
        assert api_key_field.secret is True
        assert cast(SourceFieldInputConfig, fields["organization_id"]).required is False
        # environment is a select offering both Concord hosts
        environment_field = cast(SourceFieldSelectConfig, fields["environment"])
        assert {o.value for o in environment_field.options} == {"production", "sandbox"}

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog, so the public docs can render the table list
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"] for t in self.source.get_documented_tables()}
        assert "agreements" in documented

    @parameterized.expand(["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors_present(self, fragment):
        keys = " ".join(self.source.get_non_retryable_errors().keys())
        assert fragment in keys

    def test_get_schemas_lists_all_endpoints(self):
        names = {s.name for s in self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id)}
        assert {"organizations", "agreements", "members", "folders", "clauses", "tags", "events"} <= names

    def test_get_schemas_name_filter(self):
        schemas = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=["agreements"])
        assert [s.name for s in schemas] == ["agreements"]

    @parameterized.expand(
        [
            ("agreements", True),
            ("events", True),
            ("members", False),
            ("folders", False),
            ("groups", False),
            ("tags", False),
        ]
    )
    def test_supports_incremental_only_where_server_filter_exists(self, endpoint, expected):
        schema = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=[endpoint])[0]
        assert schema.supports_incremental is expected

    def test_events_is_off_by_default_and_append(self):
        schema = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=["events"])[0]
        assert schema.should_sync_default is False
        assert schema.supports_append is True

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name, underlying, expected_ok):
        with mock.patch.object(source_module, "validate_concord_credentials", return_value=underlying):
            ok, error = self.source.validate_credentials(
                ConcordSourceConfig(api_key="k", environment="production"), self.team_id
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is ConcordResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        config = ConcordSourceConfig(api_key="secret", environment="sandbox", organization_id="55")
        inputs = mock.MagicMock()
        inputs.schema_name = "agreements"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        inputs.incremental_field = "modifiedAt"
        manager = mock.MagicMock()

        with mock.patch.object(source_module, "concord_source") as concord_source_mock:
            self.source.source_for_pipeline(config, manager, inputs)

        _args, kwargs = concord_source_mock.call_args
        assert kwargs["api_key"] == "secret"
        assert kwargs["environment"] == "sandbox"
        assert kwargs["organization_id"] == "55"
        assert kwargs["endpoint"] == "agreements"
        assert kwargs["manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == 1700000000000

    def test_source_for_pipeline_drops_incremental_value_when_not_incremental(self):
        config = ConcordSourceConfig(api_key="secret")
        inputs = mock.MagicMock()
        inputs.schema_name = "groups"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000000
        inputs.incremental_field = None

        with mock.patch.object(source_module, "concord_source") as concord_source_mock:
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        _args, kwargs = concord_source_mock.call_args
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_key_tables(self):
        descriptions = self.source.get_canonical_descriptions()
        assert "agreements" in descriptions
        assert "columns" in descriptions["agreements"]
