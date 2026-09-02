from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.source import CampfireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campfire import (
    CampfireSourceConfig,
)


def _source_inputs(
    schema_name: str, last_value: Optional[object] = None, use_incremental: bool = False
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=use_incremental,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="last_modified_at" if use_incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestCampfireSource:
    def setup_method(self) -> None:
        self.source = CampfireSource()

    def test_documented_tables_render_without_credentials(self) -> None:
        # Public docs list the table catalog through this path; it must not need I/O.
        tables = self.source.get_documented_tables()
        assert [t["name"] for t in tables] == list(ENDPOINTS)

    def test_canonical_descriptions_are_keyed_by_endpoint_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) <= set(ENDPOINTS)

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Campfire API key"))])
    def test_validate_credentials_maps_transport_result(
        self, _name: str, transport_result: bool, expected: tuple
    ) -> None:
        with patch.object(source_module, "validate_campfire_credentials", return_value=transport_result) as mock:
            result = self.source.validate_credentials(CampfireSourceConfig(api_key="k"), team_id=1)
        assert result == expected
        mock.assert_called_once_with("k", path=None)

    def test_validate_credentials_probes_the_schema_endpoint(self) -> None:
        with patch.object(source_module, "validate_campfire_credentials", return_value=True) as mock:
            self.source.validate_credentials(CampfireSourceConfig(api_key="k"), team_id=1, schema_name="contracts")
        mock.assert_called_once_with("k", path="/rr/api/v1/contracts")

    @parameterized.expand(
        [
            ("incremental", True, "2026-01-01"),
            ("full_refresh", False, None),
        ]
    )
    def test_source_for_pipeline_plumbs_inputs(self, _name: str, use_incremental: bool, expected_value) -> None:
        inputs = _source_inputs("vendors", last_value="2026-01-01", use_incremental=use_incremental)
        manager = MagicMock()
        with patch.object(source_module, "campfire_source") as mock_source:
            self.source.source_for_pipeline(CampfireSourceConfig(api_key="k"), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["endpoint"] == "vendors"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is use_incremental
        # The stored watermark must not leak into a full-refresh run.
        assert kwargs["db_incremental_field_last_value"] == expected_value
