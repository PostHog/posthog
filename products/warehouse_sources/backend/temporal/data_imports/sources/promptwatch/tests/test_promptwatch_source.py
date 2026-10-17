import re

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import SourceDriver
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.source import PromptWatchSource


def test_unknown_table() -> None:
    config = PromptWatchSourceConfig(api_key="fake-key", start_date="2026-01-01")

    result = SourceDriver(PromptWatchSource(), config).run("unknown", [])

    assert isinstance(result.raised, UnknownResourceError)
    assert re.search("unknown", str(result.raised))
    assert result.requests == []
