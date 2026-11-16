import requests
from parameterized import parameterized

from products.warehouse_sources.sources.fathom._config import FathomSourceConfig
from products.warehouse_sources.sources.fathom.source import (
    ADMIN_ONLY_MESSAGE,
    FORBIDDEN_MESSAGE,
    INVALID_KEY_MESSAGE,
    RATE_LIMITED_MESSAGE,
    UNREACHABLE_MESSAGE,
    FathomSource,
)
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network

CONFIG = FathomSourceConfig(api_key="fathom-key")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_key_at_create", None, 200, "/external/v1/meetings", (True, None)),
            ("valid_key_for_a_meeting_table", "meeting_transcripts", 200, "/external/v1/meetings", (True, None)),
            ("admin_key_for_users", "users", 200, "/external/v1/users", (True, None)),
            ("rejected_key", None, 401, "/external/v1/meetings", (False, INVALID_KEY_MESSAGE)),
            ("non_admin_key_for_users", "users", 403, "/external/v1/users", (False, ADMIN_ONLY_MESSAGE)),
            (
                "forbidden_meetings_is_not_an_admin_problem",
                None,
                403,
                "/external/v1/meetings",
                (False, FORBIDDEN_MESSAGE),
            ),
            (
                "unexpected_status",
                None,
                404,
                "/external/v1/meetings",
                (False, "Fathom returned an unexpected response (HTTP 404). Check your API key, then try again."),
            ),
        ]
    )
    def test_maps_the_probe_status(
        self,
        _name: str,
        schema_name: str | None,
        status: int,
        expected_path: str,
        expected: tuple[bool, str | None],
    ) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            result = FathomSource().validate_credentials(CONFIG, team_id=1, schema_name=schema_name)

        assert result == expected
        assert [request.path for request in network.requests_log] == [expected_path]
        assert network.requests_log[0].headers["x-api-key"] == "fathom-key"

    @parameterized.expand(
        [
            ("rate_limited", always(ScriptedResponse(status=429, json={})), RATE_LIMITED_MESSAGE),
            ("connection_error", always(requests.ConnectionError("boom")), UNREACHABLE_MESSAGE),
        ]
    )
    def test_maps_transient_failures(self, _name: str, script, expected_message: str) -> None:
        with scripted_network(script):
            result = FathomSource().validate_credentials(CONFIG, team_id=1)

        assert result == (False, expected_message)

    def test_rejects_an_unknown_table_without_a_request(self) -> None:
        with scripted_network([]) as network:
            result = FathomSource().validate_credentials(CONFIG, team_id=1, schema_name="recordings")

        assert result == (False, "Fathom has no table named recordings.")
        assert network.requests_log == []


class TestEndpointPermissions:
    @parameterized.expand(
        [
            ("non_admin_key", 403, ADMIN_ONLY_MESSAGE),
            ("admin_key", 200, None),
            ("throttled_probe_is_not_a_denial", 429, None),
        ]
    )
    def test_probes_only_the_admin_only_table(self, _name: str, status: int, users_reason: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            permissions = FathomSource().get_endpoint_permissions(CONFIG, team_id=1, endpoints=["meetings", "users"])

        assert permissions == {"meetings": None, "users": users_reason}
        assert {request.path for request in network.requests_log} == {"/external/v1/users"}
