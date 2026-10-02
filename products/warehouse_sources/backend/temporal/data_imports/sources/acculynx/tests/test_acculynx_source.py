from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.acculynx import AcculynxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.source import AcculynxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.acculynx import (
    AcculynxSourceConfig,
)


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "invalid or deactivated"),
        (403, None, True, None),
        (403, "contacts", False, "cannot access this table"),
    ],
)
def test_credential_status_mapping(
    status: int,
    schema: str | None,
    valid: bool,
    message: str | None,
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    http_send.side_effect = lambda request, **_: response(request, {"items": []}, status)
    result, error = AcculynxSource().validate_credentials(
        AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key"}),
        1,
        schema,
    )
    assert result is valid
    assert error is None if message is None else message in (error or "")
    assert http_send.call_count == 1
    request = http_send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer fake-acculynx-key"


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"api_key": "bad\nkey"}, "without spaces"),
        ({"api_key": "key\u200b"}, "unsupported characters"),
        ({"appointment_start_date": "not-a-date"}, "YYYY-MM-DD"),
        ({"appointment_start_date": "2025-03-01", "appointment_end_date": "2025-02-01"}, "after the start"),
    ],
)
def test_invalid_configuration_never_sends_credentials(
    fields: dict[str, str],
    message: str,
    http_send: MagicMock,
) -> None:
    config = AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key", **fields})
    valid, error = AcculynxSource().validate_credentials(config, 1)
    assert not valid
    assert message in (error or "")
    http_send.assert_not_called()


def test_unknown_schema_is_rejected_without_a_request(http_send: MagicMock) -> None:
    config = AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key"})
    valid, error = AcculynxSource().validate_credentials(config, 1, "unknown")
    assert not valid
    assert "Unknown AccuLynx table" in (error or "")
    http_send.assert_not_called()


def test_unexpected_probe_error_is_not_invalid_credentials(
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    http_send.side_effect = lambda request, **_: response(request, {}, 400)
    with pytest.raises(HTTPError, match="400 Client Error"):
        AcculynxSource().validate_credentials(AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key"}), 1)


@pytest.mark.parametrize("child_status", [200, 403, 404])
def test_child_permission_probe_uses_a_real_parent(
    child_status: int,
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        if request.url and "/jobs?" in request.url:
            return response(request, {"items": [{"id": "job-one"}]})
        assert request.url and "/jobs/job-one/financials?" in request.url
        return response(request, {"id": "financial-one"}, child_status)

    http_send.side_effect = send
    valid, error = AcculynxSource().validate_credentials(
        AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key"}),
        1,
        "financials",
    )
    assert valid is (child_status != 403)
    assert error is None if valid else "cannot access this table" in (error or "")


def test_incremental_configuration_cannot_silently_run_a_full_refresh(
    inputs: SourceInputs,
    manager: ResumableSourceManager[AcculynxResumeConfig],
) -> None:
    inputs.should_use_incremental_field = True
    with pytest.raises(ValueError, match="full refresh only") as error:
        AcculynxSource().source_for_pipeline(
            AcculynxSourceConfig.from_dict({"api_key": "fake-acculynx-key"}),
            manager,
            inputs,
        )
    assert any(pattern in str(error.value) for pattern in AcculynxSource().get_non_retryable_errors())
