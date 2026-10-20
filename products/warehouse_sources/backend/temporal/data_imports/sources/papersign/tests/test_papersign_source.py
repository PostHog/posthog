from typing import cast

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.papersign import (
    PapersignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.source import PapersignSource


def _config(api_token: str = "tok") -> PapersignSourceConfig:
    return PapersignSourceConfig(api_token=api_token)


class TestPapersignPipelineWiring:
    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        captured: dict[str, object] = {}

        def fake_source(**kwargs: object) -> object:
            captured.update(kwargs)
            return "sentinel"

        inputs = MagicMock()
        inputs.schema_name = "documents"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        manager = MagicMock()

        with patch.object(source_module, "papersign_source", side_effect=fake_source) as mock_source:
            result = PapersignSource().source_for_pipeline(_config(api_token="abc"), manager, inputs)

        assert cast(object, result) == "sentinel"
        mock_source.assert_called_once()
        assert captured["api_token"] == "abc"
        assert captured["endpoint"] == "documents"
        assert captured["resumable_source_manager"] is manager
        assert captured["team_id"] == 7
        assert captured["job_id"] == "job-1"
