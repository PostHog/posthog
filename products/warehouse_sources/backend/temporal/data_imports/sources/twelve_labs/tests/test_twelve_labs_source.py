from unittest.mock import patch

import structlog
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TwelveLabsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.source import TwelveLabsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs import (
    TwelveLabsResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str, last_value: object = None, should_use_incremental: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at",
        incremental_field_type=None,
        job_id="job-1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestTwelveLabsSource:
    def setup_method(self) -> None:
        self.source = TwelveLabsSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TWELVELABS

    def test_api_key_field_is_secret_password(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.required is True
        assert api_key.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("indexes", True, True),
            ("tasks", True, True),
            ("videos", False, False),
        ]
    )
    def test_schema_incremental_support(self, name: str, supports_incremental: bool, supports_append: bool) -> None:
        # Only endpoints with a genuine server-side timestamp filter are incremental; videos
        # (fan-out, unverifiable updated_at filter) ships full-refresh only.
        schema = next(
            s for s in self.source.get_schemas(TwelveLabsSourceConfig(api_key="x"), team_id=1) if s.name == name
        )
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append

    def test_videos_not_synced_by_default(self) -> None:
        # Per-index fan-out is expensive on free plans, so videos is opt-in.
        videos = next(
            s for s in self.source.get_schemas(TwelveLabsSourceConfig(api_key="x"), team_id=1) if s.name == "videos"
        )
        assert videos.should_sync_default is False

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(TwelveLabsSourceConfig(api_key="x"), team_id=1, names=["tasks"])
        assert [s.name for s in schemas] == ["tasks"]

    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("rejected_key", (False, 401), False, "Invalid Twelve Labs API key"),
            ("forbidden_key", (False, 403), False, "Invalid Twelve Labs API key"),
            # A transient outage must not be reported as a bad key, or a user gets told to replace a
            # key that is actually valid.
            (
                "rate_limited",
                (False, 429),
                False,
                "Could not connect to Twelve Labs. Check your connection and try again.",
            ),
            (
                "server_error",
                (False, 500),
                False,
                "Could not connect to Twelve Labs. Check your connection and try again.",
            ),
            (
                "network_error",
                (False, None),
                False,
                "Could not connect to Twelve Labs. Check your connection and try again.",
            ),
        ]
    )
    def test_validate_credentials(
        self, _name: str, api_result: tuple[bool, int | None], expected_ok: bool, expected_err: str | None
    ) -> None:
        with patch.object(source_module, "validate_twelve_labs_credentials", return_value=api_result):
            ok, err = self.source.validate_credentials(TwelveLabsSourceConfig(api_key="x"), team_id=1)
        assert ok is expected_ok
        assert err == expected_err

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("indexes"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TwelveLabsResumeConfig

    def test_source_for_pipeline_passes_endpoint_and_gates_incremental_value(self) -> None:
        # The last-value must only reach the transport when incremental sync is active, otherwise a
        # stale watermark would filter a full refresh.
        captured: dict[str, object] = {}

        def _fake_source(**kwargs: object) -> str:
            captured.update(kwargs)
            return "resp"

        inputs = _inputs("indexes", last_value="2026-01-01", should_use_incremental=False)
        with patch.object(source_module, "twelve_labs_source", side_effect=_fake_source):
            self.source.source_for_pipeline(TwelveLabsSourceConfig(api_key="k"), manager_stub := object(), inputs)  # type: ignore[arg-type]

        assert captured["endpoint"] == "indexes"
        assert captured["db_incremental_field_last_value"] is None
        assert captured["api_key"] == "k"
        assert manager_stub is captured["resumable_source_manager"]
