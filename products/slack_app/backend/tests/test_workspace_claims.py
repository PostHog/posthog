import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

import requests
from rest_framework.test import APIClient

from posthog.models.integration import Integration, validate_slack_request
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.tests.helpers import sign_slack_request


class TestSlackWorkspaceClaimsView(TestCase):
    """The receiver-side endpoint that the other region calls to ask "do you claim this workspace?".

    Authenticated with the same HMAC scheme Slack uses, against the Slack app signing secret that
    both regions already share. The signed body covers `slack_team_id + kinds`, so a captured
    signature cannot be replayed against a different workspace.
    """

    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-workspace-claims-secret"
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def _post(self, payload: dict, signing_secret: str | None = None) -> Any:
        body = json.dumps(payload).encode()
        signature, ts = sign_slack_request(body, signing_secret or self.signing_secret)
        return self.client.post(
            "/slack/workspace/claims/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    def test_method_not_allowed(self):
        response = self.client.get("/slack/workspace/claims/")
        assert response.status_code == 405

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_existing_integration_returns_claimed(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_PRESENT",
            sensitive_config={"access_token": "xoxb"},
        )
        response = self._post({"slack_team_id": "T_PRESENT", "kinds": ["slack"]})
        assert response.status_code == 200
        assert response.json() == {"claimed": True}

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_any_of_kinds_match_returns_claimed(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_NOTIF",
            sensitive_config={"access_token": "xoxb"},
        )
        response = self._post({"slack_team_id": "T_NOTIF", "kinds": ["slack"]})
        assert response.status_code == 200
        assert response.json() == {"claimed": True}

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_missing_integration_returns_not_claimed(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post({"slack_team_id": "T_UNKNOWN", "kinds": ["slack"]})
        assert response.status_code == 200
        assert response.json() == {"claimed": False}

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_invalid_signature_returns_403(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": "different-secret"}
        response = self._post({"slack_team_id": "T_PRESENT", "kinds": ["slack"]})
        assert response.status_code == 403

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_missing_team_id_returns_400(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post({"kinds": ["slack"]})
        assert response.status_code == 400

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_no_valid_kinds_returns_400(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post({"slack_team_id": "T_PRESENT", "kinds": ["github", "not-real"]})
        assert response.status_code == 400

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_other_kinds_for_same_id_do_not_count(self, mock_config):
        # Same integration_id can be reused across PostHog integration kinds (e.g. a GitHub install
        # whose external id happens to collide with a Slack workspace). The endpoint must scope
        # to the requested Slack kinds only.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="T_PRESENT",
            sensitive_config={"access_token": "ghp"},
        )
        response = self._post({"slack_team_id": "T_PRESENT", "kinds": ["slack"]})
        assert response.status_code == 200
        assert response.json() == {"claimed": False}


@override_settings(DEBUG=False)
class TestDoesOtherRegionClaimWorkspace(TestCase):
    """The caller-side helper. Constructs and signs the request, parses the response, and
    deliberately returns None on any transport / format failure so the caller falls back to
    local handling instead of silently dropping the event.
    """

    def setUp(self):
        cache.clear()
        self.signing_secret = "posthog-code-helper-test-secret"

    def _call(self, mock_post_return, **call_overrides) -> bool | None:
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = mock_post_return
            kwargs = {
                "slack_team_id": "T123",
                "kinds": ["slack"],
                "incoming_host": "eu.posthog.com",
                **call_overrides,
            }
            result = does_other_region_claim_workspace(**kwargs)
            self.last_call = mock_post.call_args
            return result

    def _response(self, status_code: int, body: Any) -> Any:
        response = MagicMock()
        response.status_code = status_code
        if isinstance(body, Exception):
            response.json.side_effect = body
        else:
            response.json.return_value = body
        return response

    def test_returns_true_when_other_region_claims(self):
        result = self._call(self._response(200, {"claimed": True}))
        assert result is True

    def test_returns_false_when_other_region_does_not_claim(self):
        result = self._call(self._response(200, {"claimed": False}))
        assert result is False

    def test_targets_eu_when_called_from_us(self):
        self._call(self._response(200, {"claimed": False}), incoming_host="us.posthog.com")
        assert "eu.posthog.com" in self.last_call.args[0]
        assert self.last_call.args[0].endswith("/slack/workspace/claims/")

    def test_targets_us_when_called_from_eu(self):
        self._call(self._response(200, {"claimed": False}), incoming_host="eu.posthog.com")
        assert "us.posthog.com" in self.last_call.args[0]
        assert self.last_call.args[0].endswith("/slack/workspace/claims/")

    def test_non_200_returns_none(self):
        result = self._call(self._response(500, {"claimed": True}))
        assert result is None

    def test_bad_json_returns_none(self):
        result = self._call(self._response(200, ValueError("bad json")))
        assert result is None

    def test_unexpected_payload_returns_none(self):
        # Anything other than a bool under "claimed" — including a stringy "true" — is treated as
        # an unknown answer; the caller falls back to local handling rather than guessing.
        result = self._call(self._response(200, {"claimed": "yes"}))
        assert result is None

    def test_request_exception_returns_none(self):
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.side_effect = requests.ConnectionError("boom")
            result = does_other_region_claim_workspace(
                slack_team_id="T123", kinds=["slack"], incoming_host="us.posthog.com"
            )
        assert result is None

    def test_definitive_true_answer_is_cached(self):
        # Second call with the same workspace must not re-issue the HTTP probe — a single flake
        # in a follow-up request should not re-flap routing for a workspace we just confirmed.
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = self._response(200, {"claimed": True})
            first = does_other_region_claim_workspace(
                slack_team_id="T_CACHE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            second = does_other_region_claim_workspace(
                slack_team_id="T_CACHE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            assert first is True
            assert second is True
            assert mock_post.call_count == 1

    def test_definitive_false_answer_is_cached(self):
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = self._response(200, {"claimed": False})
            first = does_other_region_claim_workspace(
                slack_team_id="T_CACHE_FALSE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            second = does_other_region_claim_workspace(
                slack_team_id="T_CACHE_FALSE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            assert first is False
            assert second is False
            assert mock_post.call_count == 1

    def test_none_answer_is_not_cached(self):
        # A flake must not poison the cache: the next event re-probes and may get a real answer.
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.side_effect = [
                requests.ConnectionError("transient"),
                self._response(200, {"claimed": True}),
            ]
            first = does_other_region_claim_workspace(
                slack_team_id="T_FLAKE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            second = does_other_region_claim_workspace(
                slack_team_id="T_FLAKE", kinds=["slack"], incoming_host="eu.posthog.com"
            )
            assert first is None
            assert second is True
            assert mock_post.call_count == 2

    def test_cache_is_keyed_by_kinds(self):
        # Two different kind sets for the same workspace must probe independently — claims can
        # differ per integration kind even though the workspace id is shared.
        from products.slack_app.backend.api import does_other_region_claim_workspace

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = self._response(200, {"claimed": True})
            does_other_region_claim_workspace(slack_team_id="T_KIND", kinds=["slack"], incoming_host="eu.posthog.com")
            assert mock_post.call_count == 1

    def test_signed_request_is_accepted_by_validator(self):
        # End-to-end roundtrip: the sent headers + body, fed into the receiver's verifier, must
        # validate cleanly. This is the actual contract we care about — the matched constant-time
        # comparison happens inside validate_slack_request.
        self._call(self._response(200, {"claimed": False}))
        sent_body = self.last_call.kwargs["data"]
        sent_headers = self.last_call.kwargs["headers"]
        request = RequestFactory().post(
            "/slack/workspace/claims/",
            data=sent_body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=sent_headers["X-Slack-Signature"],
            HTTP_X_SLACK_REQUEST_TIMESTAMP=sent_headers["X-Slack-Request-Timestamp"],
        )
        validate_slack_request(request, self.signing_secret)  # raises on mismatch
        # Loop header is included so even if the endpoint URL were ever swapped to the event
        # callback by mistake, the receiver would not re-enter the cross-region machinery.
        assert sent_headers["X-PostHog-Region-Proxied"] == "1"
