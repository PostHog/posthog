from django.test import SimpleTestCase

from parameterized import parameterized

from products.mcp_registry.backend.connect import build_connect_instructions
from products.mcp_registry.backend.models import MCPRegistryServer


def _server(**kwargs: object) -> MCPRegistryServer:
    defaults: dict[str, object] = {
        "registry_name": "io.example/demo",
        "display_name": "Demo",
        "canonical_url": "https://demo.example.com/mcp",
        "packages": [],
        "connect_overrides": {},
    }
    defaults.update(kwargs)
    return MCPRegistryServer(**defaults)


class TestConnectInstructions(SimpleTestCase):
    @parameterized.expand(
        [
            ("open_server", {"liveness": "alive_open", "auth_method": "none"}, "remote_open", "agent"),
            ("oauth_server", {"liveness": "alive_auth", "auth_method": "oauth"}, "remote_oauth", "agent"),
            ("api_key_server", {"liveness": "alive_auth", "auth_method": "api_key"}, "remote_api_key", "human"),
            (
                "package_only",
                {"canonical_url": "", "packages": [{"registry_type": "npm", "identifier": "@example/demo-mcp"}]},
                "local_package",
                "agent",
            ),
        ]
    )
    def test_recommended_method_matches_probe_results(
        self, _name: str, fields: dict, expected_method: str, expected_first_actor: str
    ) -> None:
        instructions = build_connect_instructions(_server(**fields))

        assert instructions["recommended"] == expected_method
        first_method = instructions["methods"][0]
        assert first_method["method"] == expected_method
        assert first_method["steps"][0]["actor"] == expected_first_actor

    def test_oauth_flow_keeps_the_consent_click_human(self) -> None:
        instructions = build_connect_instructions(_server(liveness="alive_auth", auth_method="oauth"))

        actors = [step["actor"] for step in instructions["methods"][0]["steps"]]
        assert actors == ["agent", "human"]

    def test_stripe_projects_partner_gets_agent_provisioning_first(self) -> None:
        server = _server(
            registry_name="com.vercel/mcp",
            display_name="Vercel",
            liveness="alive_auth",
            auth_method="oauth",
        )

        instructions = build_connect_instructions(server)

        assert instructions["recommended"] == "agent_provisioning"
        first_step = instructions["methods"][0]["steps"][0]
        assert first_step["actor"] == "agent"
        assert first_step["command"] == "stripe projects service add vercel"
        # The standard OAuth path stays available as the fallback method.
        assert instructions["methods"][1]["method"] == "remote_oauth"

    def test_similar_names_do_not_match_stripe_projects_partners(self) -> None:
        server = _server(
            registry_name="io.example/vercel-deploy-helper",
            display_name="Vercel Deploy Helper",
            liveness="alive_auth",
            auth_method="oauth",
        )

        instructions = build_connect_instructions(server)

        assert instructions["recommended"] == "remote_oauth"

    def test_agent_provisioning_is_always_preferred(self) -> None:
        server = _server(liveness="alive_auth", auth_method="api_key", supports_agent_provisioning=True)

        instructions = build_connect_instructions(server)

        assert instructions["recommended"] == "agent_provisioning"
        assert all(step["actor"] == "agent" for step in instructions["methods"][0]["steps"])

    def test_known_override_appends_extra_methods(self) -> None:
        server = _server(
            registry_name="io.github.PostHog/mcp",
            liveness="alive_auth",
            auth_method="oauth",
        )

        instructions = build_connect_instructions(server)

        assert instructions["methods"][0]["method"] == "remote_oauth"
        assert instructions["methods"][-1]["method"] == "remote_api_key"

    def test_row_overrides_replace_derived_methods(self) -> None:
        override_methods = [
            {
                "method": "cli_auth",
                "automation": "one_click",
                "summary": "Vendor CLI login mints the credential.",
                "steps": [{"actor": "agent", "description": "Run the vendor CLI login.", "command": "demo login"}],
            }
        ]
        server = _server(liveness="alive_open", auth_method="none", connect_overrides={"methods": override_methods})

        instructions = build_connect_instructions(server)

        assert instructions["methods"] == override_methods
        assert instructions["recommended"] == "cli_auth"
