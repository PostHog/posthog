import pytest
from unittest.mock import MagicMock

from sources.promptwatch._config import PromptWatchSourceConfig
from sources.promptwatch.source import PromptWatchSource
from sources.sdk import SourceInputs, UnknownResourceError


def test_unknown_table() -> None:
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = "unknown"
    config = PromptWatchSourceConfig(api_key="fake-key", start_date="2026-01-01")
    with pytest.raises(UnknownResourceError, match="unknown"):
        PromptWatchSource().source_for_pipeline(config, MagicMock(), inputs)
