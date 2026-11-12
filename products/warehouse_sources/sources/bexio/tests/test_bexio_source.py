import pytest

import requests

from products.warehouse_sources.sources.bexio._config import BexioSourceConfig
from products.warehouse_sources.sources.bexio.source import BexioSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network


@pytest.mark.parametrize(
    ("answer", "valid", "message_fragment"),
    [
        (ScriptedResponse(json={"id": 1, "email": "owner@example.com"}), True, None),
        (ScriptedResponse(status=403, json={"error_code": 403, "message": "No access rights"}), False, "refused"),
        (
            ScriptedResponse(status=401, json={"message": "Unauthorized", "request_id": "0123456789abcdef"}),
            False,
            "rejected",
        ),
        (ScriptedResponse(status=503, json={"message": "Service Unavailable"}), False, "Couldn't reach"),
        (requests.ConnectionError("connection reset"), False, "Couldn't reach"),
    ],
)
def test_validate_credentials(
    answer: ScriptedResponse | BaseException, valid: bool, message_fragment: str | None
) -> None:
    with scripted_network(always(answer)) as network:
        ok, message = BexioSource().validate_credentials(BexioSourceConfig(api_token="pat-secret"), team_id=1)

    assert ok is valid
    if message_fragment is None:
        assert message is None
    else:
        assert message is not None and message_fragment in message
    assert {request.path for request in network.requests_log} == {"/3.0/users/me"}
