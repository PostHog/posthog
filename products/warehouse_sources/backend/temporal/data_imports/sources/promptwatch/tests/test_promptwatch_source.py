import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.source import PromptWatchSource


def test_unknown_table() -> None:
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = "unknown"
    config = PromptWatchSourceConfig(api_key="fake-key", start_date="2026-01-01")
    with pytest.raises(UnknownResourceError, match="unknown"):
        PromptWatchSource().source_for_pipeline(config, MagicMock(), inputs)
