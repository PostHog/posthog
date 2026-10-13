from collections.abc import Callable

import pytest
from unittest.mock import Mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heygen import HeyGenSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.heygen import HeyGenResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.source import HeyGenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.tests.utils import sync_items


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "templates", False, "templates:read"),
        (200, "templates", True, None),
    ],
)
def test_credential_messages_and_scoped_keys(
    status: int,
    schema: str | None,
    valid: bool,
    message: str | None,
    http: Mock,
    response: Callable[..., Response],
) -> None:
    http.return_value = response({"data": []}, status)
    result, error = HeyGenSource().validate_credentials(HeyGenSourceConfig(api_key="fake-key"), 1, schema)
    assert result is valid
    if message:
        assert error is not None and message in error
    else:
        assert error is None
    assert http.call_args.args[0].url.endswith("/v3/users/me" if schema is None else "/v3/templates?limit=1")


def test_unknown_table_rejected_without_http(
    http: Mock, inputs: SourceInputs, manager: ResumableSourceManager[HeyGenResumeConfig]
) -> None:
    source = HeyGenSource()
    config = HeyGenSourceConfig(api_key="fake-key")
    assert source.validate_credentials(config, 1, "unknown") == (False, "Unknown HeyGen table: unknown")
    inputs.schema_name = "unknown"
    with pytest.raises(UnknownResourceError, match="unknown"):
        source.source_for_pipeline(config, manager, inputs)
    http.assert_not_called()


def test_permissions_identify_missing_scope(http: Mock, response: Callable[..., Response]) -> None:
    http.side_effect = [response({"data": []}), response({}, 403), response({}, 401)]
    permissions = HeyGenSource().get_endpoint_permissions(
        HeyGenSourceConfig(api_key="fake-key"), 1, ["videos", "voices", "account"]
    )
    assert permissions["videos"] is None
    assert permissions["voices"] is not None and "voices:read" in permissions["voices"]
    assert permissions["account"] is not None and "invalid or expired" in permissions["account"]


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_failures_match_terminal_errors(
    status: int,
    http: Mock,
    response: Callable[..., Response],
    inputs: SourceInputs,
    manager: ResumableSourceManager[HeyGenResumeConfig],
) -> None:
    http.return_value = response({}, status)
    source = HeyGenSource()
    resource = source.source_for_pipeline(HeyGenSourceConfig(api_key="fake-key"), manager, inputs)
    with pytest.raises(HTTPError) as error:
        list(sync_items(resource))
    assert any(pattern in str(error.value) for pattern in source.get_non_retryable_errors())
    assert http.call_count == 1


def test_full_refresh_does_not_send_stale_watermark(
    http: Mock,
    response: Callable[..., Response],
    inputs: SourceInputs,
    manager: ResumableSourceManager[HeyGenResumeConfig],
) -> None:
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = 9999999999
    inputs.incremental_field = "created_at"
    http.return_value = response({"data": [{"id": "old-video", "created_at": 1700000000}], "next_token": None})
    resource = HeyGenSource().source_for_pipeline(HeyGenSourceConfig(api_key="fake-key"), manager, inputs)
    assert list(sync_items(resource)) == [[{"id": "old-video", "created_at": 1700000000}]]
    assert http.call_args.args[0].url == "https://api.heygen.com/v3/videos?limit=100"
