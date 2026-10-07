import pytest

from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.givebutter import (
    GivebutterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.source import GivebutterSource

API = "https://api.givebutter.com/v1/"


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message"),
    [
        (200, None, True, None),
        (200, "households", True, None),
        (401, None, False, "Your Givebutter API key is invalid or expired. Generate a new API key and reconnect."),
        (403, None, True, None),
        (
            403,
            "contacts",
            False,
            "Your Givebutter API key cannot access this table. Check the key's permissions in Givebutter.",
        ),
    ],
)
def test_credential_status_maps_to_connection_result(
    requests_mock: Mocker, status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    body = {"data": [], "links": {"next": None}}
    if status == 401:
        body = {"message": "Unauthenticated."}
    elif status == 403:
        body = {"message": "This action is unauthorized."}
    requests_mock.get(
        API + (schema_name or "campaigns"), status_code=status, json=[] if schema_name == "households" else body
    )
    result = GivebutterSource().validate_credentials(GivebutterSourceConfig(api_key="test-api-key"), 1, schema_name)
    assert result == (valid, message)
    assert len(requests_mock.request_history) == 1
    assert requests_mock.last_request is not None
    assert requests_mock.last_request.qs == ({"page": ["1"]} if schema_name == "households" else {"per_page": ["1"]})
    assert requests_mock.last_request.headers["Authorization"] == "Bearer test-api-key"


@pytest.mark.parametrize("has_parent", [True, False])
def test_child_credential_probe_checks_a_real_parent(requests_mock: Mocker, has_parent: bool) -> None:
    requests_mock.get(
        API + "campaigns", json={"data": [{"id": "campaign-one"}] if has_parent else [], "links": {"next": None}}
    )
    requests_mock.get(
        API + "campaigns/campaign-one/members", status_code=403, json={"message": "This action is unauthorized."}
    )
    valid, message = GivebutterSource().validate_credentials(
        GivebutterSourceConfig(api_key="test-api-key"), 1, "campaign_members"
    )
    assert valid is (not has_parent)
    assert (message is not None) is has_parent
    assert len(requests_mock.request_history) == (2 if has_parent else 1)


@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_http_failures_are_not_retried_or_misclassified(requests_mock: Mocker, status: int) -> None:
    requests_mock.get(API + "contacts", status_code=status, json={"message": "Request rejected"})
    client = RESTClient(base_url=API, auth=BearerTokenAuth(token="test-api-key"))
    with pytest.raises(HTTPError) as error:
        next(client.paginate(path="contacts"))
    assert error_message_matches(str(error.value), GivebutterSource().get_non_retryable_errors()) is (
        status in (401, 403)
    )
    assert len(requests_mock.request_history) == 1
    if status not in (401, 403):
        with pytest.raises(HTTPError):
            GivebutterSource().validate_credentials(GivebutterSourceConfig(api_key="test-api-key"), 1, "contacts")


def test_unknown_schema_fails_before_a_request(requests_mock: Mocker) -> None:
    with pytest.raises(UnknownResourceError, match="missing_table"):
        GivebutterSource().validate_credentials(GivebutterSourceConfig(api_key="test-api-key"), 1, "missing_table")
    assert not requests_mock.called
