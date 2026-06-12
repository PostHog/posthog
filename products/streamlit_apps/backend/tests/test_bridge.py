import json

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.streamlit_apps.backend.logic.bridge import execute_bridge_query
from products.streamlit_apps.backend.tests.test_presentation import _StreamlitAppsFlagMixin


class TestExecuteBridgeQuery(BaseTest):
    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_returns_whitelisted_response(self, mock_execute):
        """Only the columns/results/types fields are surfaced — clickhouse SQL,
        hogql AST, internal timings, and modifiers must NOT leak through."""
        response = MagicMock()
        response.model_dump.return_value = {
            "results": [[1, "hello"]],
            "columns": ["id", "name"],
            "clickhouse": "SELECT ...",
            "hogql": "SELECT ...",
            "timings": {"total": 0.1},
            "modifiers": {},
            "types": [["Int64"], ["String"]],
        }
        mock_execute.return_value = response

        result = execute_bridge_query(query="SELECT 1", team_id=self.team.id)

        assert result["results"] == [[1, "hello"]]
        assert result["columns"] == ["id", "name"]
        assert result["types"] == [["Int64"], ["String"]]
        assert "clickhouse" not in result
        assert "hogql" not in result
        assert "timings" not in result
        assert "modifiers" not in result

    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_passes_query_and_team(self, mock_execute):
        response = MagicMock()
        response.model_dump.return_value = {"results": [], "columns": []}
        mock_execute.return_value = response

        execute_bridge_query(query="SELECT event FROM events", team_id=self.team.id)

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["query"] == "SELECT event FROM events"
        assert call_kwargs.kwargs["team"].id == self.team.id

    def test_invalid_team_raises(self):
        with pytest.raises(Exception):
            execute_bridge_query(query="SELECT 1", team_id=999999)


class TestStreamlitBridgeView(_StreamlitAppsFlagMixin, APIBaseTest):
    def _url(self):
        return "/api/streamlit_bridge/query/"

    def _streamlit_token(self) -> str:
        """Mint a bridge-scoped token. Iframe-scoped tokens are refused by the
        bridge, so happy-path bridge tests must mint the bridge variant."""
        from products.streamlit_apps.backend.logic.oauth import create_sandbox_bridge_token

        return create_sandbox_bridge_token(user=self.user, team_id=self.team.id)

    @parameterized.expand(
        [
            ("missing_header", {}, None, 401, "Missing or invalid Authorization header"),
            ("bad_prefix", {}, "Token abc", 401, "Missing or invalid Authorization header"),
        ]
    )
    def test_auth_failures(self, _name, body, auth_value, expected_status, expected_error):
        headers = {}
        if auth_value:
            headers["HTTP_AUTHORIZATION"] = auth_value
        response = self.client.post(
            self._url(),
            data=json.dumps(body),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == expected_status
        assert expected_error in response.json()["error"]

    def test_garbage_token_rejected(self):
        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        assert response.status_code == 401

    def test_inactive_user_token_rejected(self):
        # A bridge token outlives the minting user, so deactivating the user must
        # immediately revoke the sandbox's access to team data.
        token = self._streamlit_token()
        self.user.is_active = False
        self.user.save()

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401

    def test_non_member_user_token_rejected(self):
        # A token whose user no longer belongs to the scoped team's organization
        # must not grant query access, even with a valid bridge scope.
        from posthog.models import Organization, User

        from products.streamlit_apps.backend.logic.oauth import create_sandbox_bridge_token

        other_org = Organization.objects.create(name="Outsider Org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)
        token = create_sandbox_bridge_token(user=outsider, team_id=self.team.id)

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401

    def test_invalid_json_body(self):
        response = self.client.post(
            self._url(),
            data="not json",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._streamlit_token()}",
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["error"]

    @parameterized.expand(
        [
            ("missing_query", {}),
            ("empty_query", {"query": ""}),
            ("query_is_number", {"query": 123}),
            ("query_whitespace_only", {"query": "   "}),
        ]
    )
    def test_invalid_query_field(self, _name, body):
        response = self.client.post(
            self._url(),
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._streamlit_token()}",
        )
        assert response.status_code == 400
        assert "query" in response.json()["error"].lower()

    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_successful_query_with_oauth(self, mock_execute):
        response_obj = MagicMock()
        response_obj.model_dump.return_value = {
            "results": [[1, "test"]],
            "columns": ["id", "name"],
            "clickhouse": "SELECT ...",
            "hogql": "SELECT ...",
            "timings": {},
            "modifiers": {},
        }
        mock_execute.return_value = response_obj

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT id, name FROM persons"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._streamlit_token()}",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == [[1, "test"]]
        assert data["columns"] == ["id", "name"]
        assert "clickhouse" not in data

    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_query_execution_error_returns_400(self, mock_execute):
        mock_execute.side_effect = Exception("Parse error near 'SELCT'")

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELCT bad"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._streamlit_token()}",
        )
        assert response.status_code == 400
        assert "error" in response.json()

    def test_expired_oauth_token_rejected(self):
        from datetime import timedelta

        from django.utils import timezone

        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.utils import generate_random_oauth_access_token

        from products.streamlit_apps.backend.logic.oauth import BRIDGE_TOKEN_SCOPE, get_streamlit_oauth_app

        oauth_app = get_streamlit_oauth_app()
        token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=oauth_app,
            token=token_value,
            user=self.user,
            expires=timezone.now() - timedelta(hours=1),
            scope=BRIDGE_TOKEN_SCOPE,
            scoped_teams=[self.team.id],
        )

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()

    def test_iframe_scoped_token_rejected(self):
        """Iframe tokens (carrying `streamlit:iframe`) must not work as bridge
        credentials even though they're in the same OAuth application. This is
        the other half of the iframe-vs-bridge scope split."""
        from products.streamlit_apps.backend.logic.oauth import create_streamlit_access_token

        iframe_token = create_streamlit_access_token(user=self.user, team_id=self.team.id)

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {iframe_token.token}",
        )
        assert response.status_code == 401

    def test_multi_team_token_rejected(self):
        """Bridge tokens must be scoped to exactly one team — picking the
        first team from a multi-team list would let a token minted for team A
        silently run queries against team B."""
        from datetime import timedelta

        from django.utils import timezone

        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.utils import generate_random_oauth_access_token

        from products.streamlit_apps.backend.logic.oauth import BRIDGE_TOKEN_SCOPE, get_streamlit_oauth_app

        # Two teams, one token — the bridge should refuse even though the
        # correct team is in the list.
        other_team_id = self.team.id + 9999
        token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=get_streamlit_oauth_app(),
            token=token_value,
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope=BRIDGE_TOKEN_SCOPE,
            scoped_teams=[self.team.id, other_team_id],
        )

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        assert response.status_code == 401
        assert "exactly one team" in response.json()["error"].lower()

    def test_oauth_token_from_other_application_rejected(self):
        """A token minted against any non-streamlit OAuth app must be rejected
        even if it carries the streamlit:bridge scope and a valid scoped_teams."""
        from datetime import timedelta

        from django.utils import timezone

        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.utils import generate_random_oauth_access_token

        from products.streamlit_apps.backend.logic.oauth import BRIDGE_TOKEN_SCOPE

        other_app = OAuthApplication.objects.create(
            name="Some Other App",
            client_type="confidential",
            authorization_grant_type="authorization-code",
            redirect_uris="https://localhost",
            algorithm="RS256",
            is_first_party=True,
        )
        token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=other_app,
            token=token_value,
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope=BRIDGE_TOKEN_SCOPE,
            scoped_teams=[self.team.id],
        )

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        assert response.status_code == 401
        assert "application" in response.json()["error"].lower()

    def test_flag_disabled_returns_403(self):
        self._set_streamlit_apps_flag(False)
        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._streamlit_token()}",
        )
        assert response.status_code == 403
        assert "not available" in response.json()["error"]
