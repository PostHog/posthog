from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.folk import source as folk_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.source import FolkSource


class TestFolkValidateCredentials:
    @parameterized.expand(
        [
            # (probe status, schema_name, expected_ok)
            ("ok", 200, None, True),
            ("ok_for_schema", 200, "people", True),
            # A 403 at source-create is a genuine key scoped away from the probe resource — accept it.
            ("forbidden_at_create_accepted", 403, None, True),
            # A 403 while configuring a specific schema means no access to that resource — reject.
            ("forbidden_for_schema_rejected", 403, "people", False),
            ("unauthorized_rejected", 401, None, False),
            ("connection_failure_rejected", None, None, False),
            ("unexpected_status_rejected", 500, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, probe_status: int | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        with mock.patch.object(folk_source_module, "probe_credentials", return_value=probe_status):
            ok, error = FolkSource().validate_credentials(
                MagicMock(api_key="folk_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestFolkNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.folk.app/v1/people?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.folk.app/v1/groups?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FolkSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.folk.app/v1/people"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.folk.app/v1/companies"),
            ("read_timeout", "HTTPSConnectionPool(host='api.folk.app', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FolkSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestFolkResumableAndPipeline:
    @parameterized.expand(
        [
            # (endpoint, partition keys, partition mode)
            ("people", ["createdAt"], "datetime"),
            ("companies", ["createdAt"], "datetime"),
            ("notes", ["createdAt"], "datetime"),
            ("tasks", ["createdAt"], "datetime"),
            ("reminders", ["createdAt"], "datetime"),
            # Groups and users carry no timestamp to partition by.
            ("groups", None, None),
            ("users", None, None),
        ]
    )
    def test_source_for_pipeline_per_endpoint(
        self,
        endpoint: str,
        expected_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = False
        manager = MagicMock()
        manager.can_resume.return_value = False
        response = FolkSource().source_for_pipeline(
            MagicMock(api_key="folk_test"), resumable_source_manager=manager, inputs=inputs
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_keys == expected_keys
        assert response.partition_mode == expected_mode
