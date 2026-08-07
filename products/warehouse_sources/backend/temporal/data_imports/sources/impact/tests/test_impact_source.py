from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impact import ImpactSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.impact import ImpactResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.source import ImpactSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str = "Actions", **overrides: object) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-01T00:00:00")
    return inputs


class TestImpactSourceClass:
    def test_source_type(self) -> None:
        assert ImpactSource().source_type == ExternalDataSourceType.IMPACT

    def test_get_source_config_fields(self) -> None:
        config = ImpactSource().get_source_config
        assert config.name.value == "Impact"
        assert len(config.fields) == 2

        account_sid, auth_token = config.fields
        assert isinstance(account_sid, SourceFieldInputConfig)
        assert account_sid.name == "account_sid"
        assert account_sid.type == SourceFieldInputConfigType.TEXT
        assert account_sid.required is True
        assert account_sid.secret is False

        assert isinstance(auth_token, SourceFieldInputConfig)
        assert auth_token.name == "auth_token"
        assert auth_token.type == SourceFieldInputConfigType.PASSWORD
        assert auth_token.required is True
        assert auth_token.secret is True

        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/impact"

    def test_no_unreleased_flag(self) -> None:
        # A finished source ships visible; unreleasedSource must not be set.
        assert ImpactSource().get_source_config.unreleasedSource is not True

    def test_lists_tables_without_credentials(self) -> None:
        assert ImpactSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = ImpactSource().get_schemas(ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"Campaigns", "MediaPartners", "Invoices", "Actions"}

    @parameterized.expand(
        [
            ("Actions", True),
            ("MediaPartners", True),
            ("Campaigns", False),
            ("Invoices", False),
        ]
    )
    def test_supports_incremental_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = ImpactSource().get_schemas(
            ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1, names=[endpoint]
        )
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is expected
        assert schemas[0].supports_append is expected

    def test_names_filter_narrows_schemas(self) -> None:
        schemas = ImpactSource().get_schemas(
            ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1, names=["Campaigns"]
        )
        assert [s.name for s in schemas] == ["Campaigns"]

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = ImpactSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == {"Campaigns", "MediaPartners", "Invoices", "Actions"}

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Impact.com Account SID or Auth Token"),
        ]
    )
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with patch.object(source_module, "validate_impact_credentials", return_value=api_result):
            result = ImpactSource().validate_credentials(ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1)
        assert result == (ok, err)

    def test_get_non_retryable_errors_cover_auth(self) -> None:
        errors = ImpactSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_resumable_source_manager_bound_to_data_class(self) -> None:
        manager = ImpactSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ImpactResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock()
        inputs = _inputs(schema_name="Actions")
        with patch.object(source_module, "impact_source") as mock_impact_source:
            ImpactSource().source_for_pipeline(ImpactSourceConfig(account_sid="s", auth_token="t"), manager, inputs)

        mock_impact_source.assert_called_once()
        kwargs = mock_impact_source.call_args.kwargs
        assert kwargs["account_sid"] == "s"
        assert kwargs["auth_token"] == "t"
        assert kwargs["endpoint"] == "Actions"
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        manager = MagicMock()
        inputs = _inputs(should_use_incremental_field=False)
        with patch.object(source_module, "impact_source") as mock_impact_source:
            ImpactSource().source_for_pipeline(ImpactSourceConfig(account_sid="s", auth_token="t"), manager, inputs)

        assert mock_impact_source.call_args.kwargs["db_incremental_field_last_value"] is None
