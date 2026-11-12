from parameterized import parameterized

from products.warehouse_sources.sources.circle_so._config import CircleSoSourceConfig
from products.warehouse_sources.sources.circle_so.source import (
    INVALID_TOKEN_MESSAGE,
    PLAN_NOT_ELIGIBLE_MESSAGE,
    CircleSoSource,
)
from products.warehouse_sources.sources.sdk.testing import Script, ScriptedResponse, always, scripted_network


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", always(ScriptedResponse(status=200, json={"id": 1})), True, None),
            (
                "bad_token",
                always(ScriptedResponse(status=401, json={"message": "Your account could not be authenticated."})),
                False,
                INVALID_TOKEN_MESSAGE,
            ),
            ("plan_not_eligible", always(ScriptedResponse(status=403)), False, PLAN_NOT_ELIGIBLE_MESSAGE),
            (
                "unexpected_status",
                always(ScriptedResponse(status=500)),
                False,
                "Circle returned an unexpected response (HTTP 500). Try again in a few minutes.",
            ),
            (
                "unreachable",
                always(ConnectionError("boom")),
                False,
                "Couldn't reach Circle. Check your connection and try again.",
            ),
        ]
    )
    def test_maps_probe_result(
        self, _name: str, script: Script, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(script) as network:
            is_valid, message = CircleSoSource().validate_credentials(
                CircleSoSourceConfig(api_token="token"), team_id=1, schema_name="posts"
            )

        assert (is_valid, message) == (expected_valid, expected_message)
        # One probe covers every table, so a schema check spends no extra quota.
        assert {request.path for request in network.requests_log} == {"/api/admin/v2/community"}
        assert all(request.headers["authorization"] == "Bearer token" for request in network.requests_log)
