import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ghost import GhostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.ghost import (
    AUTH_ERROR,
    DOMAIN_ERROR,
    KEY_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.source import GhostSource

API_KEY = "0123456789abcdef01234567:" + "0123456789abcdef" * 4


@pytest.mark.parametrize(
    ("status", "schema_name", "expected"),
    [
        (200, None, (True, None)),
        (200, "members", (True, None)),
        (200, "offers", (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (403, "members", (False, PERMISSION_ERROR)),
    ],
)
def test_credential_probe_maps_auth_errors_and_checks_selected_table(
    status: int, schema_name: str | None, expected: tuple[bool, str | None]
) -> None:
    endpoint = schema_name or "posts"
    body = {endpoint: []} if status == 200 else {"errors": [{"type": "NoPermissionError", "message": "Access denied."}]}
    config = GhostSourceConfig(admin_domain="publication.example.com", admin_api_key=API_KEY)
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        assert GhostSource().validate_credentials(config, 1, schema_name=schema_name) == expected
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == f"/ghost/api/admin/{endpoint}/"
    assert request.param("limit") == (None if endpoint == "offers" else "1")


@pytest.mark.parametrize(
    ("domain", "key", "schema_name", "message"),
    [
        ("publication.example.com", "invalid", None, KEY_ERROR),
        ("publication.example.com", "id:not-hex", None, KEY_ERROR),
        ("http://publication.example.com", API_KEY, None, DOMAIN_ERROR),
        ("https://user:password@publication.example.com", API_KEY, None, DOMAIN_ERROR),
        ("https://publication.example.com/?key=example", API_KEY, None, DOMAIN_ERROR),
        ("https://publication.example.com/#fragment", API_KEY, None, DOMAIN_ERROR),
        ("https://publication.example.com:invalid", API_KEY, None, DOMAIN_ERROR),
        ("https://[invalid", API_KEY, None, DOMAIN_ERROR),
        ("publication.example.com", API_KEY, "unknown", "This Ghost table is not supported."),
    ],
)
def test_invalid_configuration_fails_before_sending_a_request(
    domain: str, key: str, schema_name: str | None, message: str
) -> None:
    config = GhostSourceConfig(admin_domain=domain, admin_api_key=key)
    with scripted_network([]) as network:
        valid, error = GhostSource().validate_credentials(config, 1, schema_name=schema_name)
    assert valid is False
    assert error is not None and message in error
    assert network.requests_log == []


def test_unexpected_probe_error_is_not_reported_as_invalid_credentials() -> None:
    config = GhostSourceConfig(admin_domain="publication.example.com", admin_api_key=API_KEY)
    with scripted_network([ScriptedResponse(status=404, json={"errors": [{"type": "NotFoundError"}]})]):
        with pytest.raises(HTTPError):
            GhostSource().validate_credentials(config, 1)


@pytest.mark.parametrize(
    ("host_valid", "expect_sync"),
    [(True, True), (False, False)],
)
def test_source_for_pipeline_rechecks_the_host_at_sync_time(host_valid: bool, expect_sync: bool) -> None:
    source = GhostSource()
    config = GhostSourceConfig(admin_domain="publication.example.com", admin_api_key=API_KEY)
    inputs = mock.MagicMock(team_id=1)
    module = "products.warehouse_sources.backend.temporal.data_imports.sources.ghost.source"
    with (
        mock.patch.object(
            source, "is_database_host_valid", return_value=(host_valid, None if host_valid else "Host not allowed")
        ) as check,
        mock.patch(f"{module}.ghost_source") as ghost_source,
    ):
        if expect_sync:
            source.source_for_pipeline(config, mock.MagicMock(), inputs)
            ghost_source.assert_called_once()
        else:
            with pytest.raises(ValueError, match="Host not allowed"):
                source.source_for_pipeline(config, mock.MagicMock(), inputs)
            ghost_source.assert_not_called()
    check.assert_called_once_with("publication.example.com", 1)
