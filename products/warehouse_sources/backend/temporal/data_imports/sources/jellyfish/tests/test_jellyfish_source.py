from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jellyfish import (
    JellyfishSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.source import JellyfishSource


class TestJellyfishSource:
    def setup_method(self) -> None:
        self.source = JellyfishSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

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

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://app.jellyfish.co/endpoints/export/v0/people/list_engineers",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://app.jellyfish.co/endpoints/export/v0/metrics/company_metrics",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("timeout", "HTTPSConnectionPool(host='app.jellyfish.co', port=443): Read timed out."),
            ("server_error", "500 Server Error for url: https://app.jellyfish.co/endpoints/export/v0/teams/list_teams"),
            ("rate_limit", "429 Too Many Requests"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

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
