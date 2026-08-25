from typing import Any

import pytest
from unittest.mock import MagicMock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.perigon import (
    PerigonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source import PerigonSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source.validate_perigon_credentials"
)


class TestPerigonSource:
    def setup_method(self) -> None:
        self.source = PerigonSource()
        self.team_id = 123

    def test_source_config_is_released_alpha(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Perigon"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # unreleasedSource hides the connector from every user — a finished source must not set it.
        assert not config.unreleasedSource

    def test_non_retryable_error_keys_match_perigon_host(self) -> None:
        # The observed HTTPError message embeds the request URL; the key must match the base host.
        observed = "401 Client Error: Unauthorized for url: https://api.perigon.io/v1/articles/all?size=100"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected_valid",
        [
            ((True, 200), None, True),
            ((False, 401), None, False),
            # 403 at source-create means the key is genuine but the plan lacks some dataset.
            ((False, 403), None, True),
            # 403 while probing a specific schema means that dataset is out of plan.
            ((False, 403), "stories", False),
            ((False, None), None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, monkeypatch: Any, probe_result: tuple[bool, int | None], schema_name: str | None, expected_valid: bool
    ) -> None:
        monkeypatch.setattr(VALIDATE_PATCH, lambda api_key, path=None: probe_result)
        config = PerigonSourceConfig(api_key="key")
        valid, error = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert error is not None

    def test_validate_credentials_probes_schema_endpoint(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_validate(api_key: str, path: str | None = None) -> tuple[bool, int | None]:
            captured["path"] = path
            return True, 200

        monkeypatch.setattr(VALIDATE_PATCH, fake_validate)
        self.source.validate_credentials(PerigonSourceConfig(api_key="key"), self.team_id, schema_name="companies")
        assert captured["path"] == "/v1/companies/all"

    def test_source_for_pipeline_plumbs_endpoint_and_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source.perigon_source",
            lambda **kwargs: captured.update(kwargs),
        )

        inputs = MagicMock()
        inputs.schema_name = "articles"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00Z"

        self.source.source_for_pipeline(PerigonSourceConfig(api_key="key"), MagicMock(), inputs)
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "articles"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-03-04T00:00:00Z"

    def test_source_for_pipeline_drops_incremental_value_when_full_refresh(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source.perigon_source",
            lambda **kwargs: captured.update(kwargs),
        )

        inputs = MagicMock()
        inputs.schema_name = "topics"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(PerigonSourceConfig(api_key="key"), MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None
