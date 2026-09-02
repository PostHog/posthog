from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clever import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.source import CleverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clever import CleverSourceConfig


def _inputs(
    schema_name: str = "Districts",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
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
    )


class TestCleverSource:
    def setup_method(self) -> None:
        self.source = CleverSource()
        self.config = CleverSourceConfig(bearer_token="test-token")

    def test_no_unreleased_source_flag(self) -> None:
        # A finished source ships visible; `unreleasedSource` hides it from every user.
        assert self.source.get_source_config.unreleasedSource is not True

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

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark leaking into a full refresh would silently skip earlier rows.
        inputs = _inputs(
            schema_name="Events",
            should_use_incremental_field=False,
            db_incremental_field_last_value="evt-123",
        )
        with patch.object(source_module, "clever_source") as mock_source:
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

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

    def test_non_retryable_errors_match_requests_error_format(self) -> None:
        # The pipeline disables a source by substring-matching these keys against the raised
        # error; they must match the message `requests.raise_for_status` actually produces.
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://api.clever.com/v3.0/districts?limit=10000"
        error = requests.HTTPError(f"401 Client Error: Unauthorized for url: {response.url}", response=response)

        assert any(key in str(error) for key in self.source.get_non_retryable_errors())
