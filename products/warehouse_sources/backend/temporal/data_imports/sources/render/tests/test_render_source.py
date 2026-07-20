from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RenderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.render import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.render.render import RenderResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.render.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.render.source import RenderSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(
    schema_name: str = "services",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
    incremental_field: str | None = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestRenderSource:
    def setup_method(self) -> None:
        self.source = RenderSource()
        self.config = RenderSourceConfig(api_key="rnd_test", owner_id="tea-123")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.RENDER

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields
        by_name = {field.name: field for field in fields}

        api_key = by_name["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True

        owner_id = by_name["owner_id"]
        assert isinstance(owner_id, SourceFieldInputConfig)
        assert owner_id.required is False

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [schema.name for schema in schemas] == list(ENDPOINTS)

    @parameterized.expand(
        [
            # Mutating resources with a server-side time filter sync incrementally via merge.
            ("services", True, False),
            ("deploys", True, False),
            # Events are immutable: append-only, never merge-incremental.
            ("events", False, True),
            # No usable watermark column: full refresh only.
            ("owners", False, False),
            ("environments", False, False),
            ("custom_domains", False, False),
        ]
    )
    def test_get_schemas_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        assert schema.supports_incremental == supports_incremental
        assert schema.supports_append == supports_append

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["services", "deploys"])
        assert {schema.name for schema in schemas} == {"services", "deploys"}

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_valid: bool) -> None:
        with patch.object(source_module, "validate_render_credentials", return_value=probe_result):
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid == expected_valid
        assert (error is None) == expected_valid

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        assert manager._data_class is RenderResumeConfig

    def test_source_for_pipeline_passes_config_and_incremental_state(self) -> None:
        inputs = _inputs(
            schema_name="deploys",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="finishedAt",
        )
        manager = MagicMock()
        with patch.object(source_module, "render_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "rnd_test"
        assert kwargs["owner_id"] == "tea-123"
        assert kwargs["endpoint"] == "deploys"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime(2026, 3, 4, tzinfo=UTC)
        assert kwargs["incremental_field"] == "finishedAt"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark leaking into a full refresh would silently skip older rows.
        inputs = _inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        with patch.object(source_module, "render_source") as mock_source:
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_non_retryable_errors_match_requests_error_format(self) -> None:
        # The pipeline disables a source by substring-matching these keys against the raised
        # error; they must match the message `requests.raise_for_status` actually produces.
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://api.render.com/v1/services?limit=100"
        error = requests.HTTPError(f"401 Client Error: Unauthorized for url: {response.url}", response=response)

        assert any(key in str(error) for key in self.source.get_non_retryable_errors())
