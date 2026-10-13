from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tally import TallySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tally import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import (
    SUBMISSION_FILTER_ALL,
    SUBMISSION_FILTER_COMPLETED,
    TALLY_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.source import TallySource


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "submissions")
    inputs.team_id = overrides.get("team_id", 123)
    inputs.job_id = overrides.get("job_id", "job-1")
    inputs.api_version = overrides.get("api_version", None)
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    inputs.incremental_field = overrides.get("incremental_field", None)
    return inputs


class TestTallySource:
    def setup_method(self) -> None:
        self.source = TallySource()
        self.team_id = 123
        self.config = TallySourceConfig(api_key="key-test")

    def test_including_partial_submissions_drops_to_full_refresh(self) -> None:
        config = TallySourceConfig(api_key="key-test", submission_filter=SUBMISSION_FILTER_ALL)
        by_name = {schema.name: schema for schema in self.source.get_schemas(config, self.team_id)}
        assert by_name["submissions"].supports_incremental is False
        assert by_name["submissions"].incremental_fields == []

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.tally.so/forms?limit=500&page=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.tally.so/forms/F1/submissions"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.tally.so/forms"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.tally.so/forms"),
            ("read_timeout", "HTTPSConnectionPool(host='api.tally.so', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("valid", True, 200, True, None),
            ("bad_key", False, 401, False, "Invalid Tally API key"),
            (
                "forbidden",
                False,
                403,
                False,
                "Your Tally API key does not have access to this data. Reconnect with a key from an account that can see these forms.",
            ),
            ("unreachable", False, None, False, "Could not reach the Tally API with this key"),
        ]
    )
    def test_validate_credentials_maps_probe_result(
        self, _name: str, probe_ok: bool, probe_status: int | None, expected_ok: bool, expected_error: str | None
    ) -> None:
        with mock.patch.object(source_module, "validate_tally_credentials", return_value=(probe_ok, probe_status)):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is expected_ok
        assert error == expected_error

    def test_source_for_pipeline_plumbs_config_and_inputs(self) -> None:
        manager = mock.MagicMock()
        inputs = _make_inputs(
            schema_name="submissions",
            team_id=99,
            job_id="job-xyz",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="submittedAt",
        )
        with mock.patch.object(source_module, "tally_source") as tally_source_fn:
            self.source.source_for_pipeline(self.config, manager, inputs)
        tally_source_fn.assert_called_once_with(
            api_key="key-test",
            api_version=TALLY_API_VERSION,
            endpoint="submissions",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="submittedAt",
            submission_filter=SUBMISSION_FILTER_COMPLETED,
        )

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark must not leak into a full-refresh run as a startDate filter.
        manager = mock.MagicMock()
        inputs = _make_inputs(
            should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01T00:00:00Z"
        )
        with mock.patch.object(source_module, "tally_source") as tally_source_fn:
            self.source.source_for_pipeline(self.config, manager, inputs)
        assert tally_source_fn.call_args.kwargs["db_incremental_field_last_value"] is None
