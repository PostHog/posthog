from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty import source as zenduty_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.source import ZendutySource


class TestZendutyGetSchemas:
    def test_names_filter(self) -> None:
        schemas = ZendutySource().get_schemas(MagicMock(), team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}


class TestZendutyValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # Zenduty returns 403 (not 401) for a bad/inactive token — reject even at source-create.
            ("forbidden_is_bad_token", 403, False),
            ("unauthorized_rejected", 401, False),
            ("connection_failure_rejected", None, False),
            ("unexpected_status_rejected", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, probe_status: int | None, expected_ok: bool) -> None:
        with mock.patch.object(zenduty_source_module, "probe_credentials", return_value=probe_status):
            ok, error = ZendutySource().validate_credentials(MagicMock(api_key="tok"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestZendutyNonRetryableErrors:
    @parameterized.expand(
        [
            ("forbidden", "403 Client Error: Forbidden for url: https://www.zenduty.com/api/account/teams/"),
            ("unauthorized", "401 Client Error: Unauthorized for url: https://www.zenduty.com/api/incidents/"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = ZendutySource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://www.zenduty.com/api/incidents/"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://www.zenduty.com/api/incidents/"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = ZendutySource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestZendutyResumableAndPipeline:
    @parameterized.expand(
        [
            # Top-level endpoints key on the object's own id...
            ("incidents", ["unique_id"]),
            ("teams", ["unique_id"]),
            # ...fan-out children key on parent team + child id, unique table-wide.
            ("services", ["_zenduty_team_id", "unique_id"]),
            ("schedules", ["_zenduty_team_id", "unique_id"]),
        ]
    )
    def test_source_for_pipeline_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        response = ZendutySource().source_for_pipeline(
            MagicMock(api_key="tok"), resumable_source_manager=MagicMock(), inputs=inputs
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # No partitioning until the stable creation-date column is confirmed per endpoint.
        assert response.partition_keys is None
        assert response.partition_mode is None
