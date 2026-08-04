from posthog.test.base import APIBaseTest

from posthog.models.scoping import team_scope

from products.mcp_store.backend.composio import COMPOSIO_HUB_URL
from products.mcp_store.backend.composio_session import connected_toolkit_slugs, has_connected_apps
from products.mcp_store.backend.models import MCPComposioConnection, MCPServerInstallation, MCPServerTemplate


class TestComposioTeamScoping(APIBaseTest):
    """The Composio models are team-scoped and fail closed, but two of their call paths carry no
    ambient team context: the public OAuth callback (a root-level route with no team in the URL)
    and the sandbox facade (Temporal activities). Both raised TeamScopeError in production."""

    def setUp(self) -> None:
        super().setUp()
        self.installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url=COMPOSIO_HUB_URL,
            display_name="Connected apps",
            auth_type="oauth",
            scope="personal",
        )
        with team_scope(self.team.id):
            self.connection = MCPComposioConnection.objects.create(
                team=self.team,
                installation=self.installation,
                toolkit_slug="asana",
                status="pending",
                connected_by=self.user,
            )

    def test_session_helpers_work_without_ambient_team_context(self) -> None:
        # Stands in for a Temporal activity resolving a sandbox's MCP servers: no request, so
        # nothing has set the team ContextVar. These must scope themselves.
        assert has_connected_apps(self.installation) is False
        assert connected_toolkit_slugs(self.installation) == []

        MCPComposioConnection.objects.for_team(self.team.id).filter(id=self.connection.id).update(status="active")

        assert has_connected_apps(self.installation) is True
        assert connected_toolkit_slugs(self.installation) == ["asana"]

    def test_callback_activates_the_connection_without_team_context(self) -> None:
        response = self.client.get(
            f"/api/mcp_store/composio_redirect/?connection={self.connection.id}"
            "&status=success&connected_account_id=ca_test123"
        )

        assert response.status_code == 302
        self.connection.refresh_from_db()
        assert self.connection.status == "active"
        assert self.connection.connected_account_id == "ca_test123"

    def test_callback_marks_a_declined_connection_failed(self) -> None:
        response = self.client.get(f"/api/mcp_store/composio_redirect/?connection={self.connection.id}&status=failed")

        assert response.status_code == 302
        self.connection.refresh_from_db()
        assert self.connection.status == "failed"

    def test_callback_refuses_a_connection_started_by_someone_else(self) -> None:
        # The connection id is the only thing the callback is given, so ownership is what stops one
        # user completing another's connection.
        with team_scope(self.team.id):
            other = MCPComposioConnection.objects.create(
                team=self.team,
                installation=self.installation,
                toolkit_slug="trello",
                status="pending",
                connected_by=None,
            )

        response = self.client.get(f"/api/mcp_store/composio_redirect/?connection={other.id}&status=success")

        assert response.status_code == 400
        other.refresh_from_db()
        assert other.status == "pending"


class TestComposioInstallationListing(APIBaseTest):
    """Every Composio app shares one installation, so connected state has to be derived rather than
    read off a row. The UI keys on an entry's `url`, and a connected app whose card still says
    "Connect" is the failure this guards."""

    def setUp(self) -> None:
        super().setUp()
        self.template = MCPServerTemplate.objects.create(
            name="LinkedIn",
            url="https://composio.dev/toolkits/linkedin",
            provider="composio",
            composio_toolkit_slug="linkedin",
            auth_type="oauth",
            is_active=True,
        )
        self.hub = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url=COMPOSIO_HUB_URL,
            display_name="Connected apps",
            auth_type="oauth",
            scope="personal",
        )
        with team_scope(self.team.id):
            self.connection = MCPComposioConnection.objects.create(
                team=self.team,
                installation=self.hub,
                template=self.template,
                toolkit_slug="linkedin",
                status="active",
                connected_by=self.user,
            )

    def _list(self) -> list[dict]:
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == 200
        payload = response.json()
        return payload["results"] if isinstance(payload, dict) else payload

    def test_connected_app_is_listed_under_its_own_toolkit_url(self) -> None:
        entries = self._list()
        urls = {entry["url"] for entry in entries}

        assert self.template.url in urls
        # The hub is plumbing, not a server anyone connected.
        assert COMPOSIO_HUB_URL not in urls

    def test_pending_connection_is_not_listed_as_connected(self) -> None:
        MCPComposioConnection.objects.for_team(self.team.id).filter(id=self.connection.id).update(status="pending")

        assert self.template.url not in {entry["url"] for entry in self._list()}

    def test_disconnecting_one_app_leaves_the_hub_and_other_apps(self) -> None:
        other_template = MCPServerTemplate.objects.create(
            name="Asana",
            url="https://composio.dev/toolkits/asana",
            provider="composio",
            composio_toolkit_slug="asana",
            auth_type="oauth",
            is_active=True,
        )
        with team_scope(self.team.id):
            MCPComposioConnection.objects.create(
                team=self.team,
                installation=self.hub,
                template=other_template,
                toolkit_slug="asana",
                status="active",
                connected_by=self.user,
            )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/mcp_server_installations/{self.connection.id}/"
        )

        assert response.status_code == 204
        assert MCPServerInstallation.objects.filter(id=self.hub.id).exists()
        assert {entry["url"] for entry in self._list()} == {other_template.url}
