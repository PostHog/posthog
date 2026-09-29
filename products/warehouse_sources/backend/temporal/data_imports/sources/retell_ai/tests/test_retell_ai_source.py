import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.models.external_data_schema import apply_incremental_lookback
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import RESTClientRetryableError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    UnknownResourceError,
    build_default_sync_settings,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retellai import (
    RetellAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.source import RetellAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.tests.conftest import response
from products.warehouse_sources.backend.types import IncrementalFieldType


@pytest.mark.parametrize("name", ["calls", "chats"])
def test_schema_lookback_refetches_recent_analysis(
    name: str, inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    source = RetellAISource()
    config = RetellAISourceConfig(api_key="fake-key")
    schemas = source.get_schemas(config, 1, names=[name])
    assert len(schemas) == 1
    sync_settings = build_default_sync_settings(schemas[0])
    assert sync_settings["sync_type"] == "incremental"
    watermark = datetime(2026, 1, 1, 1, tzinfo=UTC)
    shifted = apply_incremental_lookback(
        watermark, IncrementalFieldType.DateTime, sync_settings["incremental_field_lookback_seconds"]
    )
    inputs = replace(
        inputs, schema_name=name, should_use_incremental_field=True, db_incremental_field_last_value=shifted
    )
    http.return_value = response({"items": [], "has_more": False})
    result = source.source_for_pipeline(config, source.get_resumable_source_manager(inputs), inputs)
    assert list(result.items()) == []
    assert json.loads(http.call_args.args[1].body)["filter_criteria"]["start_timestamp"]["value"] == 1767225600000


@pytest.mark.parametrize("status", [200, 401, 403])
@pytest.mark.parametrize("name", [None, "agents", "chats", "phone_numbers", "voices"])
def test_scoped_credential_probes(status: int, name: str | None, http: MagicMock) -> None:
    http.return_value = response(
        [] if name == "voices" else {"items": [], "has_more": True, "pagination_key": "unused"}, status
    )
    success, error = RetellAISource().validate_credentials(
        RetellAISourceConfig(api_key="fake-key"), 1, schema_name=name
    )
    assert success is (status == 200 or (status == 403 and name is None))
    if success:
        assert error is None
    elif status == 401:
        assert error is not None and "invalid or expired" in error
    else:
        assert error is not None and "permissions" in error
    assert http.call_count == 1
    request = http.call_args.args[1]
    if name in (None, "chats"):
        assert json.loads(request.body)["limit"] == 1
    elif name != "voices":
        assert parse_qs(urlsplit(request.url).query)["limit"] == ["1"]


@pytest.mark.parametrize("key", ["", "fake key", "fake-key\n", "clé-example", "fake\rkey"])
def test_malformed_api_keys_fail_before_http(key: str, http: MagicMock) -> None:
    success, error = RetellAISource().validate_credentials(RetellAISourceConfig(api_key=key), 1)
    assert success is False
    assert error is not None and "valid Retell AI API key" in error
    http.assert_not_called()


@pytest.mark.parametrize("status", [400, 429, 500])
def test_probe_errors_are_not_reported_as_invalid_credentials(
    status: int, http: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    http.return_value = response({}, status)
    with pytest.raises(HTTPError if status == 400 else RESTClientRetryableError):
        RetellAISource().validate_credentials(RetellAISourceConfig(api_key="fake-key"), 1)


def test_unknown_table_fails_before_http(inputs: SourceInputs, http: MagicMock) -> None:
    source = RetellAISource()
    inputs = replace(inputs, schema_name="unknown-table")
    with pytest.raises(UnknownResourceError):
        source.source_for_pipeline(
            RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
        )
    http.assert_not_called()
