import pytest

from products.warehouse_sources.sources.planning_center._config import PlanningCenterSourceConfig
from products.warehouse_sources.sources.planning_center.source import PlanningCenterSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, route, scripted_network

_CONFIG = PlanningCenterSourceConfig(application_id="app-id", secret="pat-secret")

_UNAUTHORIZED = ScriptedResponse(
    status=401, json={"errors": [{"status": "401", "title": "Unauthorized", "detail": "Not authorized"}]}
)
_FORBIDDEN = ScriptedResponse(
    status=403, json={"errors": [{"status": "403", "title": "Forbidden", "detail": "You do not have access"}]}
)
_OK = ScriptedResponse(json={"data": [], "included": [], "meta": {"total_count": 0}})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("schema_name", "answer", "expected_path", "expected"),
        [
            (None, _OK, "/people/v2", (True, None)),
            (None, _FORBIDDEN, "/people/v2", (True, None)),
            (
                None,
                _UNAUTHORIZED,
                "/people/v2",
                (
                    False,
                    "Planning Center rejected the application ID or secret. Check the personal access token, then try again.",
                ),
            ),
            (
                None,
                ScriptedResponse(status=500, json={}),
                "/people/v2",
                (False, "Couldn't reach Planning Center to check the token. Try again in a few minutes."),
            ),
            ("donations", _OK, "/giving/v2/donations", (True, None)),
            (
                "donations",
                _FORBIDDEN,
                "/giving/v2/donations",
                (
                    False,
                    "Your Planning Center user can't read Giving data. "
                    "Give the user access to Giving in Planning Center, or deselect the Giving tables.",
                ),
            ),
            ("plans", _OK, "/services/v2/service_types", (True, None)),
        ],
    )
    def test_maps_the_probe_status(
        self,
        schema_name: str | None,
        answer: ScriptedResponse,
        expected_path: str,
        expected: tuple[bool, str | None],
    ) -> None:
        with scripted_network(always(answer)) as network:
            assert PlanningCenterSource().validate_credentials(_CONFIG, team_id=1, schema_name=schema_name) == expected

        assert {request.path for request in network.requests_log} == {expected_path}
        assert network.requests_log[0].headers["authorization"].startswith("Basic ")

    def test_unknown_schema_is_rejected_without_a_request(self) -> None:
        with scripted_network([]) as network:
            assert PlanningCenterSource().validate_credentials(_CONFIG, team_id=1, schema_name="nope") == (
                False,
                "Planning Center has no table named nope.",
            )

        assert network.requests_log == []


class TestEndpointPermissions:
    def test_probes_each_product_once_and_flags_its_tables(self) -> None:
        with scripted_network(route({"/people/v2/people": [_OK], "/giving/v2/donations": [_FORBIDDEN]})) as network:
            permissions = PlanningCenterSource().get_endpoint_permissions(
                _CONFIG, team_id=1, endpoints=["people", "emails", "donations", "funds"]
            )

        giving_message = (
            "Your Planning Center user can't read Giving data. "
            "Give the user access to Giving in Planning Center, or deselect the Giving tables."
        )
        assert permissions == {"people": None, "emails": None, "donations": giving_message, "funds": giving_message}
        assert [request.path for request in network.requests_log] == ["/people/v2/people", "/giving/v2/donations"]
