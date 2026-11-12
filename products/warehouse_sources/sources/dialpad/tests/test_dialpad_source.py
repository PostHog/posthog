import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.dialpad._config import DialpadSourceConfig
from products.warehouse_sources.sources.dialpad.source import DialpadSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network

CONFIG = DialpadSourceConfig(api_key="dp_test_key")
UNAUTHORIZED = ScriptedResponse(status=401, json={"error": {"code": 401, "message": "Unauthorized"}})
FORBIDDEN = ScriptedResponse(status=403, json={"error": {"code": 403, "message": "Forbidden"}})


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)


@parameterized.expand(
    [
        ("valid_key", None, ScriptedResponse(json={"id": "1"}), "/api/v2/company", (True, None)),
        (
            "rejected_key",
            None,
            UNAUTHORIZED,
            "/api/v2/company",
            (False, "Dialpad rejected this API key. Check the key and try again."),
        ),
        (
            "user_level_key_at_create",
            None,
            FORBIDDEN,
            "/api/v2/company",
            (
                False,
                "This key can't read your whole Dialpad company. "
                "Create a company API key in the Dialpad admin settings and try again.",
            ),
        ),
        (
            "forbidden_for_a_table",
            "calls",
            FORBIDDEN,
            "/api/v2/call",
            (False, "Your API key can't read this table. It needs a company API key with the `calls:list` scope."),
        ),
        (
            "server_error",
            "users",
            ScriptedResponse(status=500, json={}),
            "/api/v2/users",
            (False, "Dialpad returned an error (HTTP 500). Try again in a few minutes."),
        ),
        (
            "network_failure",
            None,
            requests.ConnectionError("connection refused"),
            "/api/v2/company",
            (False, "Couldn't reach Dialpad. Try again in a few minutes."),
        ),
    ]
)
def test_validate_credentials(
    _name: str,
    schema_name: str | None,
    answer: ScriptedResponse | Exception,
    expected_path: str,
    expected: tuple[bool, str | None],
) -> None:
    with scripted_network(always(answer)) as network:
        assert DialpadSource().validate_credentials(CONFIG, team_id=1, schema_name=schema_name) == expected

    assert {request.path for request in network.requests_log} == {expected_path}


def test_validate_credentials_rejects_an_unknown_table_without_a_request() -> None:
    with scripted_network(always(ScriptedResponse(json={}))) as network:
        assert DialpadSource().validate_credentials(CONFIG, team_id=1, schema_name="faxes") == (
            False,
            "Dialpad has no table named faxes.",
        )

    assert network.requests_log == []


def test_endpoint_permissions_report_only_denied_tables() -> None:
    answers = {
        "/api/v2/call": FORBIDDEN,
        "/api/v2/numbers": UNAUTHORIZED,
        "/api/v2/users": ScriptedResponse(json={"items": []}),
        "/api/v2/offices": ScriptedResponse(status=429, json={}),
        "/api/v2/rooms": ScriptedResponse(status=500, json={}),
    }

    with scripted_network(lambda request: answers[request.path]):
        permissions = DialpadSource().get_endpoint_permissions(
            CONFIG, team_id=1, endpoints=["calls", "numbers", "users", "offices", "rooms", "faxes"]
        )

    assert permissions == {
        "calls": "Your API key can't read this table. It needs a company API key with the `calls:list` scope.",
        "numbers": "Your API key can't read this table. It needs a company admin API key.",
        "users": None,
        "offices": None,
        "rooms": None,
        "faxes": None,
    }
