import pytest
from unittest.mock import MagicMock

import structlog
import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.source import (
    RevolutMerchantSource,
)


def inputs(schema_name: str, api_version: str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="created_at",
        incremental_field_type=None,
        job_id="test-job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
        api_version=api_version,
    )


@pytest.mark.parametrize("environment,host", [("production", "merchant"), ("sandbox", "sandbox-merchant")])
def test_full_refresh_and_probe_honor_environment_and_version(
    requests_mock: requests_mock.Mocker, environment: str, host: str
) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": environment})
    requests_mock.get(f"https://{host}.revolut.com/api/customers", json={"customers": [{"id": "customer-1"}]})
    resume_manager = MagicMock(spec=ResumableSourceManager)
    resume_manager.can_resume.return_value = False
    result = source.source_for_pipeline(config, resume_manager, inputs("customers", "2026-04-20"))
    assert list(result.items()) == [[{"id": "customer-1"}]]
    assert requests_mock.last_request.qs == {"limit": ["500"]}
    assert requests_mock.last_request.headers["Revolut-Api-Version"] == "2026-04-20"
    assert source.validate_credentials(config, 1, api_version="2026-04-20") == (True, None)
    assert requests_mock.last_request.headers["Revolut-Api-Version"] == "2026-04-20"
    assert requests_mock.last_request.qs == {"limit": ["1"]}


@pytest.mark.parametrize("status,message", [(401, "Secret API key"), (403, "permissions"), (400, "API version")])
def test_sync_auth_and_version_failures_match_terminal_errors(
    requests_mock: requests_mock.Mocker, status: int, message: str
) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "production"})
    requests_mock.get("https://merchant.revolut.com/api/customers", status_code=status, json={"code": "error"})
    resume_manager = MagicMock(spec=ResumableSourceManager)
    resume_manager.can_resume.return_value = False
    with pytest.raises(HTTPError) as error:
        list(source.source_for_pipeline(config, resume_manager, inputs("customers")).items())
    matches = [text for pattern, text in source.get_non_retryable_errors().items() if pattern in str(error.value)]
    assert len(matches) == 1 and message in matches[0]
    assert requests_mock.call_count == 1
    resume_manager.save_state.assert_not_called()


def test_unknown_schema_fails_before_network(requests_mock: requests_mock.Mocker) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "production"})
    with pytest.raises(UnknownResourceError, match="unknown_table"):
        source.source_for_pipeline(config, MagicMock(), inputs("unknown_table"))
    assert requests_mock.call_count == 0


def test_environment_cannot_retarget_credentials(requests_mock: requests_mock.Mocker) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "https://example.com"})
    with pytest.raises(ValueError, match="Production or Sandbox"):
        source.validate_credentials(config, 1)
    assert requests_mock.call_count == 0
