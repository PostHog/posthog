import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metaplane import (
    MetaplaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source import MetaplaneSource


class TestMetaplaneSource:
    def setup_method(self) -> None:
        self.source = MetaplaneSource()
        self.team_id = 123
        self.config = MetaplaneSourceConfig(api_key="mp-test-key")

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint == "monitor_evaluations"
        assert schema.supports_incremental is expected_incremental
        # Merge-only everywhere: the evaluation cursor may re-pull the watermark row,
        # which append mode would materialize as a duplicate.
        assert schema.supports_append is False
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["createdAt"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert [s.name for s in schemas] == ["monitors"]

    @pytest.mark.parametrize(
        "is_valid, expected_valid, expected_has_message",
        [
            (True, True, False),
            (False, False, True),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source.validate_metaplane_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        is_valid: bool,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = is_valid
        valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_key)
