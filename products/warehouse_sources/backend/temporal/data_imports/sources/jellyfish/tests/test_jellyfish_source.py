from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JellyfishSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.jellyfish import JellyfishResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.source import JellyfishSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJellyfishSource:
    def setup_method(self) -> None:
        self.source = JellyfishSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.JELLYFISH

    def test_config_fields(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_token"}
        assert fields["api_token"].required is True
        assert fields["api_token"].secret is True

    def test_source_is_released(self) -> None:
        # `unreleasedSource=True` hides the connector from every user — a finished source must
        # never carry it (newness is expressed via releaseStatus instead).
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus is not None

    def test_docs_url_matches_doc_filename(self) -> None:
        assert self.source.get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/jellyfish"

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

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

    def test_documented_tables_render_from_static_catalog(self) -> None:
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["engineers"]["description"]
        assert tables["engineers"]["sync_methods"] == ["Full refresh"]

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

    def test_resumable_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is JellyfishResumeConfig

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
