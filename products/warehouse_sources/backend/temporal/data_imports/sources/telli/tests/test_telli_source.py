from collections.abc import Iterable
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import MagicMock

import responses
from requests.exceptions import HTTPError
from responses import matchers

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telli import TelliSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.source import TelliSource
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.telli import TelliResumeConfig, telli_source


@pytest.mark.parametrize(
    "schema_name,path,params",
    [
        (None, "/v1/verify-api-key", {}),
        ("calls", "/v1/list-calls", {"limit": "1"}),
        ("contacts", "/v2/contacts", {"limit": "1"}),
        ("agents", "/v2/agents", {"limit": "1"}),
        ("contact_properties", "/v2/properties/contacts", {}),
        ("phone_numbers", "/v1/phone-numbers", {}),
    ],
)
def test_validation_probes_only_requested_resource(schema_name: str | None, path: str, params: dict[str, str]) -> None:
    with responses.RequestsMock() as http:
        http.get(
            f"https://api.telli.com{path}",
            json={"message": "API key is valid", "data": [], "calls": [], "next_cursor": "unused"},
            match=[matchers.query_param_matcher(params)],
        )
        assert TelliSource().validate_credentials(
            TelliSourceConfig(api_key="test-telli-key"), 1, schema_name=schema_name
        ) == (True, None)
        assert len(http.calls) == 1
        assert http.calls[0].request.headers["Authorization"] == "Bearer test-telli-key"


@pytest.mark.parametrize(
    "status,schema_name,expected_message",
    [
        (401, None, "invalid or expired"),
        (402, None, "paid telli plan"),
        (403, None, "does not have permission"),
        (401, "contacts", "invalid or expired"),
        (402, "contacts", "paid telli plan"),
        (403, "contacts", "does not have permission"),
    ],
)
def test_auth_errors_are_actionable_and_terminal(status: int, schema_name: str | None, expected_message: str) -> None:
    source = TelliSource()
    path = "/v2/contacts" if schema_name else "/v1/verify-api-key"
    with responses.RequestsMock() as http:
        http.get(f"https://api.telli.com{path}", status=status, json={"message": "Access denied"})
        valid, message = source.validate_credentials(
            TelliSourceConfig(api_key="test-telli-key"), 1, schema_name=schema_name
        )
        assert valid is False
        assert message and expected_message in message
        assert len(http.calls) == 1

    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    with responses.RequestsMock() as http:
        http.get("https://api.telli.com/v2/contacts", status=status, json={"message": "Access denied"})
        response = telli_source("test-telli-key", "contacts", 1, "test-job", manager)
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[object], response.items()))
        assert error_message_matches(str(error.value), source.get_non_retryable_errors())
        manager.save_state.assert_not_called()


def test_resumable_manager_uses_telli_state() -> None:
    inputs = cast(SourceInputs, SimpleNamespace(logger=MagicMock(), team_id=1, job_id="test-job"))
    manager = TelliSource().get_resumable_source_manager(inputs)

    assert isinstance(manager, ResumableSourceManager)
    assert manager._inputs is inputs
    assert manager._data_class is TelliResumeConfig


def test_unexpected_validation_error_is_not_invalid_credentials() -> None:
    with responses.RequestsMock() as http:
        http.get("https://api.telli.com/v1/verify-api-key", status=400, json={"message": "Bad request"})
        with pytest.raises(HTTPError):
            TelliSource().validate_credentials(TelliSourceConfig(api_key="test-telli-key"), 1)


@pytest.mark.parametrize("operation", ["validate", "sync"])
def test_unknown_schema_fails_before_http(operation: str) -> None:
    source = TelliSource()
    config = TelliSourceConfig(api_key="test-telli-key")
    with responses.RequestsMock() as http, pytest.raises(UnknownResourceError):
        if operation == "validate":
            source.validate_credentials(config, 1, schema_name="unknown")
        else:
            source.source_for_pipeline(
                config,
                MagicMock(spec=ResumableSourceManager),
                cast(SourceInputs, SimpleNamespace(schema_name="unknown", team_id=1, job_id="test-job")),
            )
    assert not http.calls
