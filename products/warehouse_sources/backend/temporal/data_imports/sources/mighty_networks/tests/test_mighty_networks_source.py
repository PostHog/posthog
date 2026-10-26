from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mightynetworks import (
    MightyNetworksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source import MightyNetworksSource


class TestMightyNetworksSource:
    def setup_method(self) -> None:
        self.source = MightyNetworksSource()
        self.team_id = 123
        self.config = MightyNetworksSourceConfig(network_id="1234", api_key="key")

    def test_connection_host_fields_cover_network_id(self) -> None:
        # network_id is where the stored api_key is sent; retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["network_id"]

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_token", (False, 401), None, False, "Invalid credentials"),
            (
                "missing_scope_at_create",
                (False, 403),
                None,
                True,
                None,
            ),
            (
                "missing_scope_for_schema",
                (False, 403),
                "Members",
                False,
                "Your Mighty Networks API key doesn't have permission to read this table.",
            ),
            (
                "wrong_network_id",
                (False, 404),
                None,
                False,
                "Mighty Networks couldn't find that network ID. Check the network ID and try again.",
            ),
            ("transport_error", (False, None), None, False, "Invalid credentials"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        mock_return: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        status_code = mock_return[1]
        script: Script = (
            always(ConnectionError("boom")) if status_code is None else [ScriptedResponse(status=status_code)]
        )
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert {request.path for request in network.requests_log} == {"/admin/v1/networks/1234/me"}
        assert all(request.headers["authorization"] == "Bearer key" for request in network.requests_log)

    @parameterized.expand([("letters", "abc"), ("empty", ""), ("path_injection", "1234/../evil"), ("float", "12.34")])
    def test_validate_credentials_rejects_malformed_network_id(self, _name: str, network_id: str) -> None:
        config = MightyNetworksSourceConfig(network_id=network_id, api_key="key")

        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert "network ID" in (error_message or "")
        assert network.requests_log == []

    def test_get_endpoint_permissions_probes_every_requested_endpoint(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(status=200),
                ScriptedResponse(status=403, json={"message": "missing scope"}),
                ScriptedResponse(status=200),
            ]
        ) as network:
            permissions = self.source.get_endpoint_permissions(
                self.config, self.team_id, ["Members", "Purchases", "SpaceMembers"]
            )

        assert permissions == {"Members": None, "Purchases": "missing scope", "SpaceMembers": None}
        # A fan-out table probes the parent list it walks, since its own path needs a parent id.
        assert [request.path for request in network.requests_log] == [
            "/admin/v1/networks/1234/members",
            "/admin/v1/networks/1234/purchases",
            "/admin/v1/networks/1234/spaces",
        ]
        assert [request.param("per_page") for request in network.requests_log] == ["1", "1", "1"]
        assert all(request.headers["authorization"] == "Bearer key" for request in network.requests_log)
