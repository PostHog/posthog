from collections.abc import Callable
from dataclasses import replace

import pytest

from requests import PreparedRequest
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.source import AlegraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alegra import AlegraSourceConfig


@pytest.mark.parametrize(
    "status, expected_valid, message",
    [(200, True, None), (401, False, "authentication failed"), (403, False, "denied access")],
)
def test_credential_status_mapping(
    config: AlegraSourceConfig,
    http_boundary: Callable[..., list[PreparedRequest]],
    status: int,
    expected_valid: bool,
    message: str | None,
) -> None:
    sent = http_boundary([(status, {"name": "Example company"})])
    valid, error = AlegraSource().validate_credentials(config, team_id=1, schema_name="items")
    assert valid == expected_valid
    if message is None:
        assert error is None
    else:
        assert error is not None and message in error
    assert len(sent) == 1
    assert sent[0].url == "https://api.alegra.com/api/v1/company"


@pytest.mark.parametrize("status", [400, 404])
def test_non_auth_probe_errors_propagate(
    config: AlegraSourceConfig, http_boundary: Callable[..., list[PreparedRequest]], status: int
) -> None:
    http_boundary([(status, {"code": "INVALID_REQUEST"})])
    with pytest.raises(HTTPError):
        AlegraSource().validate_credentials(config, team_id=1)


@pytest.mark.parametrize("email, token", [("", "fake-token"), ("warehouse@example.com", "  ")])
def test_empty_credentials_do_not_reach_vendor(
    email: str, token: str, http_boundary: Callable[..., list[PreparedRequest]]
) -> None:
    sent = http_boundary([])
    valid, error = AlegraSource().validate_credentials(AlegraSourceConfig(email=email, api_token=token), team_id=1)
    assert not valid
    assert error == "Enter your Alegra email and API token."
    assert sent == []


def test_incremental_configuration_fails_before_extraction(
    config: AlegraSourceConfig, inputs: SourceInputs, http_boundary: Callable[..., list[PreparedRequest]]
) -> None:
    sent = http_boundary([])
    source = AlegraSource()
    with pytest.raises(ValueError, match="Alegra only supports full refresh"):
        source.source_for_pipeline(
            config,
            source.get_resumable_source_manager(inputs),
            replace(inputs, should_use_incremental_field=True, incremental_field="date"),
        )
    assert sent == []
