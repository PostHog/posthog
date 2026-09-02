from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impact import ImpactSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.source import ImpactSource


def _inputs(schema_name: str = "Actions", **overrides: object) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-01T00:00:00")
    inputs.api_version = overrides.get("api_version", None)
    return inputs


class TestImpactSourceClass:
    def test_no_unreleased_flag(self) -> None:
        # A finished source ships visible; unreleasedSource must not be set.
        assert ImpactSource().get_source_config.unreleasedSource is not True

    def test_lists_tables_without_credentials(self) -> None:
        assert ImpactSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = ImpactSource().get_schemas(ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1)
        names = {s.name for s in schemas}
        assert names == {
            "Campaigns",
            "MediaPartners",
            "Invoices",
            "Actions",
            "ActionUpdates",
            "Contracts",
            "InvoiceLineItems",
            "InvoiceDetailedLineItems",
        }

    @parameterized.expand(
        [
            ("Actions", True),
            ("MediaPartners", True),
            ("ActionUpdates", True),
            ("Campaigns", False),
            ("Invoices", False),
            ("Contracts", False),
            ("InvoiceLineItems", False),
            ("InvoiceDetailedLineItems", False),
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
        assert names == {
            "Campaigns",
            "MediaPartners",
            "Invoices",
            "Actions",
            "ActionUpdates",
            "Contracts",
            "InvoiceLineItems",
            "InvoiceDetailedLineItems",
        }

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

    def test_default_version_is_14(self) -> None:
        assert ImpactSource.default_version == "14"
        assert ImpactSource.supported_versions == ("v1", "14")

    @parameterized.expand(
        [
            ("unpinned_resolves_to_default", None, "14"),
            ("legacy_pin_honored", "v1", "v1"),
            ("dated_pin_honored", "14", "14"),
        ]
    )
    def test_source_for_pipeline_passes_resolved_version(self, _name: str, pin: Optional[str], expected: str) -> None:
        manager = MagicMock()
        inputs = _inputs(schema_name="Actions", api_version=pin)
        with patch.object(source_module, "impact_source") as mock_impact_source:
            ImpactSource().source_for_pipeline(ImpactSourceConfig(account_sid="s", auth_token="t"), manager, inputs)

        assert mock_impact_source.call_args.kwargs["api_version"] == expected

    @parameterized.expand(
        [
            ("unpinned_resolves_to_default", None, "14"),
            ("legacy_pin_honored", "v1", "v1"),
        ]
    )
    def test_validate_credentials_passes_resolved_version(self, _name: str, pin: Optional[str], expected: str) -> None:
        with patch.object(source_module, "validate_impact_credentials", return_value=True) as mock_validate:
            ImpactSource().validate_credentials(
                ImpactSourceConfig(account_sid="s", auth_token="t"), team_id=1, api_version=pin
            )
        assert mock_validate.call_args.args[2] == expected
