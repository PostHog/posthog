from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TravisCISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source import TravisCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.travis_ci import TravisCIResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> TravisCISourceConfig:
    return TravisCISourceConfig(api_token="travis-token")


class TestTravisCISource:
    def setup_method(self) -> None:
        self.source = TravisCISource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TRAVISCI

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert [f.name for f in config.fields] == ["api_token"]
        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.secret is True

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = {s.name for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas == set(ENDPOINTS)

    @parameterized.expand(
        [
            # Builds and jobs page newest-first and stop at the id watermark; repositories and
            # branches expose no usable cursor, so they are full refresh only.
            ("repositories", False),
            ("builds", True),
            ("jobs", True),
            ("branches", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_branches_not_synced_by_default(self) -> None:
        # Branches re-walk every repository's full branch list each sync, so they must stay
        # opt-in rather than being force-enabled by one-shot source creation.
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas["branches"].should_sync_default is False

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["builds"])
        assert [s.name for s in schemas] == ["builds"]

    @parameterized.expand(
        [
            # Travis answers 403 (not 401) for bad tokens, so the 403 mapping is the one that
            # actually stops endless retries on revoked credentials.
            (
                "access_denied",
                "403 Client Error: Forbidden for url: https://api.travis-ci.com/repo/1/builds?limit=100",
            ),
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.travis-ci.com/user"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.travis-ci.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.travis-ci.com/repos"),
            ("rate_limited", "Travis CI API error (retryable): status=429"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TravisCIResumeConfig

    def test_validate_credentials_delegates_with_token(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source.validate_travis_ci_credentials",
            return_value=(True, None),
        ) as mock_validate:
            result = self.source.validate_credentials(_config(), team_id=self.team_id, schema_name="builds")
        assert result == (True, None)
        mock_validate.assert_called_once_with("travis-token")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 278462667
        manager = MagicMock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source.travis_ci_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["api_token"] == "travis-token"
        assert captured["endpoint"] == "builds"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == 278462667
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "repositories"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 278462667

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source.travis_ci_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
