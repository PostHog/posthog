from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clever import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.settings import (
    CLEVER_API_VERSION_V3_0,
    CLEVER_API_VERSION_V3_1,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.source import CleverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clever import CleverSourceConfig


def _inputs(
    schema_name: str = "Districts",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
    api_version: str | None = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
        api_version=api_version,
    )


class TestCleverSource:
    def setup_method(self) -> None:
        self.source = CleverSource()
        self.config = CleverSourceConfig(bearer_token="test-token")

    @parameterized.expand(
        [
            # Clever's entity endpoints have no server-side timestamp filter: full refresh only.
            ("Districts", False, False),
            ("Schools", False, False),
            ("Users", False, False),
            ("Sections", False, False),
            ("Courses", False, False),
            ("Terms", False, False),
            ("Contacts", False, False),
            # /events is a real delta feed with a stable id cursor.
            ("Events", True, True),
        ]
    )
    def test_get_schemas_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        assert schema.supports_incremental == supports_incremental
        assert schema.supports_append == supports_append

    def test_source_for_pipeline_passes_config_and_incremental_state(self) -> None:
        inputs = _inputs(
            schema_name="Events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="evt-123",
        )
        manager = MagicMock()
        with patch.object(source_module, "clever_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["bearer_token"] == "test-token"
        assert kwargs["endpoint"] == "Events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "evt-123"

    def test_new_sources_default_to_v3_1(self) -> None:
        assert self.source.supported_versions == (CLEVER_API_VERSION_V3_0, CLEVER_API_VERSION_V3_1)
        assert self.source.default_version == CLEVER_API_VERSION_V3_1

    @parameterized.expand(
        [
            ("pinned_v3_0", CLEVER_API_VERSION_V3_0, CLEVER_API_VERSION_V3_0),
            ("pinned_v3_1", CLEVER_API_VERSION_V3_1, CLEVER_API_VERSION_V3_1),
            ("unpinned", None, CLEVER_API_VERSION_V3_1),
        ]
    )
    def test_source_for_pipeline_passes_resolved_api_version(
        self, _name: str, pinned: str | None, expected: str
    ) -> None:
        with patch.object(source_module, "clever_source") as mock_source:
            self.source.source_for_pipeline(self.config, MagicMock(), _inputs(api_version=pinned))

        assert mock_source.call_args.kwargs["api_version"] == expected

    @parameterized.expand(
        [
            ("pinned_v3_0", CLEVER_API_VERSION_V3_0, CLEVER_API_VERSION_V3_0),
            ("pinned_v3_1", CLEVER_API_VERSION_V3_1, CLEVER_API_VERSION_V3_1),
            ("pre_creation", None, CLEVER_API_VERSION_V3_1),
        ]
    )
    def test_validate_credentials_uses_resolved_api_version(
        self, _name: str, pinned: str | None, expected: str
    ) -> None:
        with patch.object(source_module, "validate_clever_credentials", return_value=(True, None)) as mock_validate:
            self.source.validate_credentials(self.config, team_id=1, api_version=pinned)

        mock_validate.assert_called_once_with("test-token", expected)

    @parameterized.expand(
        [
            ("Districts", None),
            ("Schools", "created"),
            ("Users", "created"),
            ("Sections", "created"),
            ("Courses", None),
            ("Terms", None),
            ("Contacts", "created"),
            ("Events", "created"),
        ]
    )
    def test_source_for_pipeline_partitions_on_the_stable_created_field(
        self, endpoint: str, expected_partition_key: str | None
    ) -> None:
        with patch.object(source_module, "clever_source") as mock_source:
            mock_source.return_value.name = endpoint
            mock_source.return_value.column_hints = None
            response = self.source.source_for_pipeline(self.config, MagicMock(), _inputs(schema_name=endpoint))

        if expected_partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition_key]
            assert response.partition_mode == "datetime"
