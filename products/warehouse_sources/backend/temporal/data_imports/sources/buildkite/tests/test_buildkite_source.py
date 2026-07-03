from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import BuildkiteResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source import BuildkiteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BuildkiteSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> BuildkiteSourceConfig:
    return BuildkiteSourceConfig(api_access_token="bkua_test", organization="my-org")


class TestBuildkiteSource:
    def setup_method(self) -> None:
        self.source = BuildkiteSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BUILDKITE

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        field_names = {f.name for f in config.fields}
        assert field_names == {"api_access_token", "organization"}
        # The token is the secret; the org slug is not.
        by_name = {f.name: f for f in config.fields}
        token_field = by_name["api_access_token"]
        org_field = by_name["organization"]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert isinstance(org_field, SourceFieldInputConfig)
        assert token_field.secret is True
        assert org_field.secret is False

    def test_connection_host_fields_includes_organization(self) -> None:
        # The token is sent to api.buildkite.com against <organization>, so retargeting the
        # organization must force re-entry of the token.
        assert self.source.connection_host_fields == ["organization"]

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = {s.name for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas == set(ENDPOINTS)

    @parameterized.expand(
        [
            # Only builds exposes a server-side timestamp filter, so it's the only incremental endpoint.
            ("builds", True),
            ("organizations", False),
            ("pipelines", False),
            ("agents", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["builds"])
        assert [s.name for s in schemas] == ["builds"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.buildkite.com/v2/organizations/my-org/builds?per_page=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.buildkite.com/v2/organizations/my-org/agents",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.buildkite.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.buildkite.com/v2"),
            ("rate_limited", "Buildkite API error (retryable): status=429"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Each declared endpoint should have a curated description so it isn't sent to the LLM.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BuildkiteResumeConfig

    def test_validate_credentials_delegates_with_org_and_token(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.validate_buildkite_credentials",
            return_value=(True, None),
        ) as mock_validate:
            result = self.source.validate_credentials(_config(), team_id=self.team_id, schema_name="builds")
        assert result == (True, None)
        mock_validate.assert_called_once_with("bkua_test", "my-org", "builds")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = MagicMock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["api_access_token"] == "bkua_test"
        assert captured["organization"] == "my-org"
        assert captured["endpoint"] == "builds"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert captured["incremental_field"] == "created_at"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "pipelines"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source.buildkite_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
