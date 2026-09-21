import json
from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration, validate_slack_request
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.tests.helpers import sign_slack_request


class TestSlackWorkspaceClaimsView(TestCase):
    """The receiver-side endpoint that the other region calls to ask "do you claim this workspace?".

    Authenticated with the same HMAC scheme Slack uses, against the Slack app signing secret that
    both regions already share. The signature covers every request filter, so a captured request
    cannot be replayed against a different workspace or project.
    """

    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-workspace-claims-secret"
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def _post(self, payload: dict, signing_secret: str | None = None) -> Any:
        body = json.dumps(payload).encode()
        signed = sign_slack_request(body, signing_secret or self.signing_secret)
        return self.client.post(
            "/slack/workspace/claims/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
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
        assert response.json()["claimed"] is True

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
        assert response.json()["claimed"] is True

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_missing_integration_returns_not_claimed(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post({"slack_team_id": "T_UNKNOWN", "kinds": ["slack"]})
        assert response.status_code == 200
        assert response.json()["claimed"] is False

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
        assert response.json()["claimed"] is False


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


class TestSlackWorkspaceClaimsGranularFacts(TestCase):
    """The granular half of the claims response: whether this region holds the event's thread
    task and when its routing defaults were last touched. These facts feed the sender's
    precedence ladder, so a wrong answer here routes real events to the wrong region."""

    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-granular-claims-secret"
        self.organization = Organization.objects.create(name="Granular Org")
        self.team = Team.objects.create(organization=self.organization, name="Granular Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_GRANULAR",
            sensitive_config={"access_token": "xoxb"},
        )

    def _post(self, payload: dict) -> Any:
        body = json.dumps(payload).encode()
        signed = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/workspace/claims/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    def _create_thread_mapping(self, channel: str, thread_ts: str) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        user = User.objects.create(email="claims-owner@example.com")
        task = Task.objects.create(
            team=self.team,
            title="Claims test task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=user,
            repository="org/repo",
        )
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_GRANULAR",
            channel=channel,
            thread_ts=thread_ts,
            task=task,
            task_run=task_run,
            mentioning_slack_user_id="U_OWNER",
        )

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_reports_thread_and_default_facts(self, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        self._create_thread_mapping("C_THREAD", "111.222")
        user_row = SlackSettings.objects.create(
            slack_workspace_id="T_GRANULAR",
            slack_user_id="U_OWNER",
            default_integration=self.integration,
        )
        workspace_row = SlackSettings.objects.create(
            slack_workspace_id="T_GRANULAR",
            slack_user_id=None,
            default_integration=self.integration,
        )
        response = self._post(
            {
                "slack_team_id": "T_GRANULAR",
                "kinds": ["slack"],
                "slack_user_id": "U_OWNER",
                "channel": "C_THREAD",
                "thread_ts": "111.222",
            }
        )
        assert response.status_code == 200
        assert response.json() == {
            "claimed": True,
            "thread_claim": True,
            "user_default_updated_at": user_row.updated_at.isoformat(),
            "workspace_default_updated_at": workspace_row.updated_at.isoformat(),
        }

    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_prefs_only_row_and_foreign_thread_do_not_count(self, mock_config):
        # A personal row carrying only AI preferences inherits the routing default, so it says
        # nothing about which region the user's project lives in; a mapping for a different
        # thread must not claim this one.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        self._create_thread_mapping("C_OTHER", "999.999")
        SlackSettings.objects.create(
            slack_workspace_id="T_GRANULAR",
            slack_user_id="U_OWNER",
            default_integration=None,
            ai_preferences={"model": "opus"},
        )
        response = self._post(
            {
                "slack_team_id": "T_GRANULAR",
                "kinds": ["slack"],
                "slack_user_id": "U_OWNER",
                "channel": "C_THREAD",
                "thread_ts": "111.222",
            }
        )
        assert response.status_code == 200
        assert response.json() == {
            "claimed": True,
            "thread_claim": False,
            "user_default_updated_at": None,
            "workspace_default_updated_at": None,
        }

    @parameterized.expand(["slack_user_id", "channel", "thread_ts"])
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_non_string_context_field_returns_400(self, key, mock_config):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        response = self._post({"slack_team_id": "T_GRANULAR", "kinds": ["slack"], key: 123})
        assert response.status_code == 400


_OLDER = datetime(2026, 1, 1, tzinfo=UTC)
_NEWER = datetime(2026, 2, 1, tzinfo=UTC)


def _claims(**kwargs) -> Any:
    from products.slack_app.backend.api import RegionClaims

    return RegionClaims(claimed=True, granular=True, **kwargs)


class TestCompareRegionClaims(SimpleTestCase):
    """The precedence ladder both regions must agree on: thread beats user default beats
    workspace default; within a rung the fresher side wins and exact ties go to US."""

    @parameterized.expand(
        [
            ("local_thread", _claims(thread_claim=True), _claims(), False, "local"),
            ("remote_thread", _claims(), _claims(thread_claim=True), False, "other"),
            ("both_threads_from_eu_go_to_us", _claims(thread_claim=True), _claims(thread_claim=True), False, "other"),
            ("both_threads_from_us_stay", _claims(thread_claim=True), _claims(thread_claim=True), True, "local"),
            (
                "thread_beats_fresher_user_default",
                _claims(thread_claim=True),
                _claims(user_default_updated_at=_NEWER),
                False,
                "local",
            ),
            ("local_user_default_only", _claims(user_default_updated_at=_OLDER), _claims(), False, "local"),
            ("remote_user_default_only", _claims(), _claims(user_default_updated_at=_OLDER), False, "other"),
            (
                "fresher_user_default_wins",
                _claims(user_default_updated_at=_OLDER),
                _claims(user_default_updated_at=_NEWER),
                False,
                "other",
            ),
            (
                "user_default_tie_from_eu_goes_to_us",
                _claims(user_default_updated_at=_NEWER),
                _claims(user_default_updated_at=_NEWER),
                False,
                "other",
            ),
            (
                "user_default_beats_fresher_workspace_default",
                _claims(user_default_updated_at=_OLDER),
                _claims(workspace_default_updated_at=_NEWER),
                False,
                "local",
            ),
            ("remote_workspace_default_only", _claims(), _claims(workspace_default_updated_at=_OLDER), False, "other"),
            ("no_facts", _claims(), _claims(), False, None),
        ]
    )
    def test_ladder(self, _name, local, remote, local_is_us, expected):
        from products.slack_app.backend.api import compare_region_claims

        assert compare_region_claims(local, remote, local_is_us=local_is_us) == expected


@override_settings(DEBUG=False)
class TestProbeOtherRegionClaims(SimpleTestCase):
    """Caller-side parsing and caching of the granular claims probe. The parse must survive an
    old-deploy receiver (bool-only payload) and malformed timestamps, and context probes must
    not share cache entries with workspace-only probes."""

    def setUp(self):
        cache.clear()
        self.signing_secret = "posthog-code-probe-test-secret"

    def _response(self, body: Any) -> Any:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = body
        return response

    def _probe(self, body: Any, **kwargs) -> Any:
        from products.slack_app.backend.api import probe_other_region_claims

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = self._response(body)
            result = probe_other_region_claims(
                slack_team_id="T_PROBE", kinds=["slack"], incoming_host="eu.posthog.com", **kwargs
            )
            self.last_post = mock_post
            return result

    def test_old_style_payload_is_not_granular(self):
        claims = self._probe({"claimed": True})
        assert claims is not None
        assert claims.claimed is True
        assert claims.granular is False

    def test_granular_payload_parses_timestamps(self):
        claims = self._probe(
            {
                "claimed": True,
                "thread_claim": False,
                "user_default_updated_at": "2026-02-01T00:00:00+00:00",
                "workspace_default_updated_at": None,
            }
        )
        assert claims is not None
        assert claims.granular is True
        assert claims.user_default_updated_at == _NEWER
        assert claims.workspace_default_updated_at is None

    @parameterized.expand([("junk", "not-a-date"), ("naive", "2026-02-01T00:00:00")])
    def test_bad_timestamp_reads_as_absent(self, _name, value):
        # A naive timestamp is rejected too: comparing it with an aware local one would raise
        # inside the webhook request.
        claims = self._probe({"claimed": True, "thread_claim": True, "user_default_updated_at": value})
        assert claims is not None
        assert claims.user_default_updated_at is None

    def test_context_probe_has_its_own_cache_entry_and_signed_body(self):
        from products.slack_app.backend.api import probe_other_region_claims

        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            mock_post.return_value = self._response({"claimed": True, "thread_claim": True})
            probe_other_region_claims(slack_team_id="T_PROBE", kinds=["slack"], incoming_host="eu.posthog.com")
            probe_other_region_claims(
                slack_team_id="T_PROBE",
                kinds=["slack"],
                incoming_host="eu.posthog.com",
                slack_user_id="U1",
                channel="C1",
                thread_ts="1.2",
            )
            # A cache hit for the workspace-only probe must not answer the thread-scoped one.
            assert mock_post.call_count == 2
            sent = json.loads(mock_post.call_args.kwargs["data"])
            assert sent["slack_user_id"] == "U1"
            assert sent["channel"] == "C1"
            assert sent["thread_ts"] == "1.2"


@override_settings(DEBUG=False)
class TestGranularRouteDecision(TestCase):
    """The granular decision as a whole: probe, local facts, ladder, and the workspace-rule
    fallback that reuses the probe's answer. Every failure along the path must come out as
    None so routing behaves exactly as it did before the ladder existed."""

    def setUp(self):
        cache.clear()
        self.signing_secret = "posthog-code-decision-test-secret"
        self.organization = Organization.objects.create(name="Decision Org")
        self.team = Team.objects.create(organization=self.organization, name="Decision Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_DECIDE",
            sensitive_config={"access_token": "xoxb"},
        )

    def _response(self, body: Any) -> Any:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = body
        return response

    def _decide(
        self,
        remote_body: Any,
        *,
        flag_enabled: bool = True,
        proxied: bool = False,
        incoming_host: str = "eu.posthog.com",
        region: str = "EU",
    ) -> Any:
        from products.slack_app.backend.api import _granular_route_decision, _region_routing_context

        context = _region_routing_context(
            [self.integration], slack_user_id="U_DECIDE", channel="C_DECIDE", thread_ts="1.2"
        )
        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post") as mock_post,
            patch("products.slack_app.backend.api.get_instance_region", return_value=region),
            patch(
                "products.slack_app.backend.api.is_slack_app_granular_region_routing_enabled",
                return_value=flag_enabled,
            ),
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            if isinstance(remote_body, Exception):
                mock_post.side_effect = remote_body
            else:
                mock_post.return_value = self._response(remote_body)
            result = _granular_route_decision(
                "T_DECIDE", ["slack"], context, proxied=proxied, incoming_host=incoming_host
            )
            self.probe_count = mock_post.call_count
            return result

    def _granular_remote(self, **overrides) -> dict:
        return {
            "claimed": True,
            "thread_claim": False,
            "user_default_updated_at": None,
            "workspace_default_updated_at": None,
            **overrides,
        }

    def test_flag_off_skips_the_probe_entirely(self):
        assert self._decide(self._granular_remote(), flag_enabled=False) is None
        assert self.probe_count == 0

    def test_proxied_event_never_probes(self):
        assert self._decide(self._granular_remote(), proxied=True) is None
        assert self.probe_count == 0

    def test_probe_failure_falls_back(self):
        assert self._decide(requests.ConnectionError("down")) is None

    def test_old_deploy_response_falls_back(self):
        assert self._decide({"claimed": True}) is None

    def test_unclaimed_remote_keeps_event_local(self):
        assert self._decide(self._granular_remote(claimed=False)) == "local"

    def test_remote_thread_claim_defers(self):
        assert self._decide(self._granular_remote(thread_claim=True)) == "other"

    def test_local_user_default_keeps_event_despite_remote_workspace_claim(self):
        # The behavior the ladder exists for: EU no longer yields to US when the user's
        # default project lives in EU.
        SlackSettings.objects.create(
            slack_workspace_id="T_DECIDE",
            slack_user_id="U_DECIDE",
            default_integration=self.integration,
        )
        assert self._decide(self._granular_remote()) == "local"

    def test_remote_fresher_user_default_defers(self):
        SlackSettings.objects.create(
            slack_workspace_id="T_DECIDE",
            slack_user_id="U_DECIDE",
            default_integration=self.integration,
        )
        SlackSettings.objects.filter(slack_workspace_id="T_DECIDE").update(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        assert self._decide(self._granular_remote(user_default_updated_at="2026-02-01T00:00:00+00:00")) == "other"

    def test_no_facts_from_eu_defers_to_us_without_second_probe(self):
        assert self._decide(self._granular_remote()) == "other"
        assert self.probe_count == 1

    def test_no_facts_from_us_stays_local(self):
        result = self._decide(self._granular_remote(), incoming_host="us.posthog.com", region="US")
        assert result == "local"


@override_settings(DEBUG=False)
class TestResolveRegionRouteGranularWiring(TestCase):
    """resolve_region_or_terminal_route must act on the ladder's verdict: keep the event
    without consulting the US-precedence fallback on "local", and actually proxy on "other"."""

    def setUp(self):
        cache.clear()
        self.signing_secret = "posthog-code-wiring-test-secret"
        self.organization = Organization.objects.create(name="Wiring Org")
        self.team = Team.objects.create(organization=self.organization, name="Wiring Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_WIRE",
            sensitive_config={"access_token": "xoxb"},
        )

    def _resolve(self, remote_body: dict) -> tuple[Any, int]:
        from products.slack_app.backend.api import _region_routing_context, resolve_region_or_terminal_route

        request = RequestFactory().post("/slack/events/", data=b"{}", content_type="application/json")
        context = _region_routing_context([self.integration], slack_user_id="U_WIRE", channel="C_WIRE", thread_ts="1.2")
        probe_response = MagicMock()
        probe_response.status_code = 200
        probe_response.json.return_value = remote_body
        proxy_response = MagicMock()
        proxy_response.status_code = 200
        with (
            patch("products.slack_app.backend.api.SlackIntegration.slack_config") as mock_config,
            patch("products.slack_app.backend.api.requests.post", return_value=probe_response),
            patch("products.slack_app.backend.api.requests.request", return_value=proxy_response) as mock_proxy,
            patch("products.slack_app.backend.api.get_instance_region", return_value="EU"),
            patch(
                "products.slack_app.backend.api.is_slack_app_granular_region_routing_enabled",
                return_value=True,
            ),
        ):
            mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
            route = resolve_region_or_terminal_route(
                request,
                "T_WIRE",
                candidates_present=True,
                kinds=["slack"],
                proxied=False,
                other_domain="us.posthog.com",
                incoming_host="eu.posthog.com",
                can_defer=True,
                context=context,
            )
            return route, mock_proxy.call_count

    def test_local_verdict_keeps_event_without_proxy(self):
        SlackSettings.objects.create(
            slack_workspace_id="T_WIRE",
            slack_user_id="U_WIRE",
            default_integration=self.integration,
        )
        route, proxy_calls = self._resolve(
            {
                "claimed": True,
                "thread_claim": False,
                "user_default_updated_at": None,
                "workspace_default_updated_at": None,
            }
        )
        assert route is None
        assert proxy_calls == 0

    def test_other_verdict_proxies(self):
        from products.slack_app.backend.api import ROUTE_PROXIED

        route, proxy_calls = self._resolve(
            {
                "claimed": True,
                "thread_claim": True,
                "user_default_updated_at": None,
                "workspace_default_updated_at": None,
            }
        )
        assert route == ROUTE_PROXIED
        assert proxy_calls == 1
