import json
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token

WEBHOOK_TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {"type": "webhook"},
}

EVENT_TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {"type": "event"},
}


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
class TestStripeAppOAuthWorkflowAccess(APIBaseTest):
    """
    The PostHog Stripe app's Trigger PostHog Workflow custom action lists hog
    flows via the Django API and fires them via the public webhook. This test
    guards the Django-side prerequisites: the OAuth token minted for the Stripe
    app (using the exact StripeIntegration.SCOPES string) must be able to list
    webhook-triggered workflows and retrieve a workflow with its variables so
    the extension can render a dynamic form.

    The public webhook endpoint itself is served by the CDP API in Node.js and
    is covered by that service's own tests — we do not re-test dispatch here.
    """

    def setUp(self):
        super().setUp()

        self.webhook_flow = HogFlow.objects.create(
            team=self.team,
            name="Webhook flow",
            status=HogFlow.State.ACTIVE,
            trigger={"type": "webhook"},
            actions=[WEBHOOK_TRIGGER_ACTION],
            edges=[],
            variables=[{"key": "customer_email", "default": ""}],
        )
        self.event_flow = HogFlow.objects.create(
            team=self.team,
            name="Event flow",
            status=HogFlow.State.ACTIVE,
            trigger={"type": "event"},
            actions=[EVENT_TRIGGER_ACTION],
            edges=[],
        )

        oauth_app = OAuthApplication.objects.create(
            name="PostHog Stripe App (test)",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        self.access_token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=oauth_app,
            token=self.access_token_value,
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope=StripeIntegration.SCOPES,
            scoped_teams=[self.team.id],
        )

        # Drop the session auth that APIBaseTest sets up so we exercise the OAuth path.
        self.client.logout()

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token_value}"}

    def test_stripe_integration_scopes_include_hog_flow_read(self):
        # Guard against a future refactor that trims StripeIntegration.SCOPES.
        # Both scopes are currently granted and both are used by the Stripe app.
        assert "hog_flow:read" in StripeIntegration.SCOPES
        assert "hog_flow:write" in StripeIntegration.SCOPES

    def test_token_lists_webhook_triggered_workflows(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/?trigger={json.dumps({'type': 'webhook'})}",
            **self._auth_headers(),
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        ids = [w["id"] for w in response.json()["results"]]
        assert str(self.webhook_flow.id) in ids
        assert str(self.event_flow.id) not in ids

    def test_token_lists_all_workflows_without_filter(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/",
            **self._auth_headers(),
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        ids = [w["id"] for w in response.json()["results"]]
        assert str(self.webhook_flow.id) in ids
        assert str(self.event_flow.id) in ids

    def test_token_retrieves_workflow_with_variables(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/{self.webhook_flow.id}/",
            **self._auth_headers(),
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["id"] == str(self.webhook_flow.id)
        # Drives the dynamic_schema the extension builds in get_form_state.
        assert any(v.get("key") == "customer_email" for v in body["variables"])

    def test_list_response_follows_limit_offset_pagination_shape(self):
        # The extension paginates by following response.next until it's null,
        # so the response must use LimitOffsetPagination (default at
        # posthog/settings/web.py). Lock down the shape.
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/?limit=1",
            **self._auth_headers(),
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert "count" in body
        assert "next" in body
        assert "previous" in body
        assert "results" in body
        assert len(body["results"]) == 1

    def test_token_without_hog_flow_scope_cannot_list(self):
        # Negative: a token with the same shape but no hog_flow scope must be rejected.
        # This isolates the dependency on hog_flow:read in the Stripe scope string.
        oauth_app = OAuthApplication.objects.create(
            name="Narrower App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        narrow_token = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=oauth_app,
            token=narrow_token,
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope="project:read",
            scoped_teams=[self.team.id],
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/",
            HTTP_AUTHORIZATION=f"Bearer {narrow_token}",
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ), response.content
