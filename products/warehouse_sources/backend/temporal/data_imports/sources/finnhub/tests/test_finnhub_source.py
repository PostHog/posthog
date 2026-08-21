from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.source import FinnhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finnhub import (
    FinnhubSourceConfig,
)


def _config(**overrides: Any) -> FinnhubSourceConfig:
    base: dict[str, Any] = {"api_key": "key", "symbols": "AAPL", "exchange": "US"}
    base.update(overrides)
    return FinnhubSourceConfig.from_dict(base)


class TestGetSchemas:
    def test_only_company_news_is_incremental(self) -> None:
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"company_news"}
        assert schemas["company_news"].incremental_fields[0]["field"] == "datetime"


if __name__ == "__main__":
    pytest.main([__file__])
