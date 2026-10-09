import pytest

from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
    OneHundredMsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.onehundredms import (
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.source import OneHundredMsSource


@pytest.mark.parametrize("status,expected", [(200, None), (401, "app access key"), (403, "denied access")])
@pytest.mark.parametrize("schema,path", [(None, "sessions"), ("live_streams", "live-streams")])
def test_credentials_probe_and_error_mapping(
    requests_mock: Mocker, status: int, expected: str | None, schema: str | None, path: str
) -> None:
    config = OneHundredMsSourceConfig(app_access_key="example-key", app_secret="example-secret-for-tests-only-12345")
    requests_mock.get(f"https://api.100ms.live/v2/{path}", status_code=status, json={"data": [], "last": "more"})
    source = OneHundredMsSource()
    valid, message = source.validate_credentials(config, 1, schema_name=schema)
    assert valid is (status == 200)
    assert requests_mock.call_count == 1
    assert requests_mock.last_request is not None
    assert requests_mock.last_request.qs == {"limit": ["10"]}
    assert requests_mock.last_request.headers["Authorization"].startswith("Bearer ")
    if expected:
        assert expected in (message or "")
        with pytest.raises(HTTPError) as error:
            validate_credentials(config, "v2", schema)
        assert any(
            pattern in str(error.value) and text == message
            for pattern, text in source.get_non_retryable_errors().items()
        )
        assert config.app_secret not in str(error.value)
    else:
        assert message is None


@pytest.mark.parametrize("status", [429, 500])
def test_transient_probe_errors_are_not_invalid_credentials(requests_mock: Mocker, status: int) -> None:
    config = OneHundredMsSourceConfig(app_access_key="example-key", app_secret="example-secret-for-tests-only-12345")
    requests_mock.get("https://api.100ms.live/v2/sessions", status_code=status, json={"code": status})
    with pytest.raises(RESTClientRetryableError):
        OneHundredMsSource().validate_credentials(config, 1)
    assert requests_mock.call_count == 1
