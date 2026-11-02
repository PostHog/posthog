import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gorgias import (
    GorgiasSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source import GorgiasSource


def _config() -> GorgiasSourceConfig:
    return GorgiasSourceConfig(gorgias_domain="acme", email="you@acme.com", api_key="key")


class TestGorgiasSource:
    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        result = SourceDriver(GorgiasSource(), _config()).run(
            "customers", [ScriptedResponse(json={"data": [], "meta": {"next_cursor": None}})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        "error_message",
        [
            "Gorgias API error (retryable): status=429, endpoint=ticket_field_values",
            "Gorgias API error (retryable): status=500, endpoint=tickets",
            "Gorgias API error (retryable): status=503, endpoint=customers",
        ],
    )
    def test_retryable_errors_match_exhausted_backoff(self, error_message: str) -> None:
        # `fetch` already retries 429/5xx internally with backoff; once those attempts are
        # exhausted, this must stay classified as retryable so it doesn't get tracked as noise.
        retryable_errors = GorgiasSource().get_retryable_errors()
        assert any(pattern in error_message for pattern in retryable_errors)
