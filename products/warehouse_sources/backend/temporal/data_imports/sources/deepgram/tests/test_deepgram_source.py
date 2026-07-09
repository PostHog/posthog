from datetime import UTC, datetime

from unittest.mock import patch

import structlog
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import DeepgramResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.source import DeepgramSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepgramSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = structlog.get_logger()


def _config() -> DeepgramSourceConfig:
    return DeepgramSource().parse_config({"api_key": "dg-key"})


def _inputs(schema_name: str = "requests", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": LOGGER,
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSourceType:
    def test_source_type(self) -> None:
        assert DeepgramSource().source_type == ExternalDataSourceType.DEEPGRAM


class TestSourceConfig:
    def test_basic_metadata(self) -> None:
        config = DeepgramSource().get_source_config
        assert config.label == "Deepgram"
        assert config.unreleasedSource is True
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/deepgram"

    def test_fields(self) -> None:
        fields = {f.name: f for f in DeepgramSource().get_source_config.fields}
        assert set(fields) == {"api_key"}

        api_key = fields["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True


class TestGetSchemas:
    def test_all_schemas(self) -> None:
        schemas = {s.name: s for s in DeepgramSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"projects", "api_keys", "members", "balances", "requests"}

    @parameterized.expand(
        [
            ("projects", False),
            ("api_keys", False),
            ("members", False),
            ("balances", False),
            ("requests", True),
        ]
    )
    def test_incremental_support(self, endpoint: str, supports: bool) -> None:
        schemas = {s.name: s for s in DeepgramSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports
        assert schemas[endpoint].supports_append is supports

    def test_requests_has_created_incremental_field(self) -> None:
        schemas = {s.name: s for s in DeepgramSource().get_schemas(_config(), team_id=1)}
        assert [f["field"] for f in schemas["requests"].incremental_fields] == ["created"]

    def test_filter_by_names(self) -> None:
        schemas = DeepgramSource().get_schemas(_config(), team_id=1, names=["members"])
        assert [s.name for s in schemas] == ["members"]


class TestCanonicalDescriptions:
    def test_descriptions_cover_only_known_endpoints(self) -> None:
        # A renamed endpoint must not leave orphaned canonical descriptions behind.
        assert set(DeepgramSource().get_canonical_descriptions()) == set(ENDPOINTS)
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)


class TestValidateCredentials:
    @parameterized.expand(
        [
            (True, (True, None)),
            (False, (False, "Invalid Deepgram API key")),
        ]
    )
    def test_delegates_to_transport(self, transport_result: bool, expected: tuple[bool, str | None]) -> None:
        with patch.object(source_module, "validate_deepgram_credentials", return_value=transport_result) as validate:
            assert DeepgramSource().validate_credentials(_config(), team_id=1) == expected
        assert validate.call_args.args == ("dg-key",)


class TestResumableSourceManager:
    def test_manager_bound_to_resume_config(self) -> None:
        manager = DeepgramSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DeepgramResumeConfig


class TestSourceForPipeline:
    def test_plumbs_config_and_inputs(self) -> None:
        source = DeepgramSource()
        inputs = _inputs(
            schema_name="requests",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        manager = source.get_resumable_source_manager(inputs)

        with patch.object(source_module, "deepgram_source") as mock_source:
            source.source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "dg-key"
        assert kwargs["endpoint"] == "requests"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime(2026, 1, 1, tzinfo=UTC)

    def test_incremental_value_dropped_for_full_refresh(self) -> None:
        source = DeepgramSource()
        inputs = _inputs(
            schema_name="members",
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        with patch.object(source_module, "deepgram_source") as mock_source:
            source.source_for_pipeline(_config(), source.get_resumable_source_manager(inputs), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
