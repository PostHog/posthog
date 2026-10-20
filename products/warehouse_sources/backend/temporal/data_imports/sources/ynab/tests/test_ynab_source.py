import pytest
from unittest.mock import MagicMock

import responses

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ynab import YnabSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.source import YnabSource


@pytest.mark.parametrize("operation", ["validate", "sync"])
@responses.activate
def test_unknown_schema_fails_before_http(operation: str) -> None:
    source = YnabSource()
    config = YnabSourceConfig(api_key="fake-ynab-token")
    with pytest.raises(UnknownResourceError, match="unknown_table"):
        if operation == "validate":
            source.validate_credentials(config, 1, schema_name="unknown_table")
        else:
            inputs = MagicMock(schema_name="unknown_table", api_version="v1")
            source.source_for_pipeline(config, MagicMock(), inputs)
    assert len(responses.calls) == 0
