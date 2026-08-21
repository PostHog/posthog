from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jellyfish import (
    JellyfishSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.source import JellyfishSource


class TestJellyfishSource:
    def setup_method(self) -> None:
        self.source = JellyfishSource()
        self.team_id = 123

    def test_get_schemas_covers_every_endpoint_full_refresh_only(self) -> None:
        # The export API has no updated-since cursor and its date filters couldn't be verified
        # against a live account, so no endpoint may advertise incremental sync.
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["engineers"])
        assert [s.name for s in schemas] == ["engineers"]

    @pytest.mark.parametrize("probe_result,expected_valid", [(True, True), (False, False)])
    def test_validate_credentials(self, probe_result: bool, expected_valid: bool, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_jellyfish_credentials", lambda api_token: probe_result)
        config = JellyfishSourceConfig(api_token="t")
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_source_for_pipeline_plumbs_args(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_jellyfish_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "jellyfish_source", fake_jellyfish_source)

        config = JellyfishSourceConfig(api_token="my-token")
        manager = MagicMock()
        inputs = MagicMock()
        inputs.schema_name = "engineers"

        result: Any = self.source.source_for_pipeline(config, manager, inputs)

        assert result == "response"
        assert captured["api_token"] == "my-token"
        assert captured["endpoint"] == "engineers"
        assert captured["resumable_source_manager"] is manager
