from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.database.database import _compute_system_table_access_decision

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value
from posthog.rbac.user_access_control import UserAccessControl

from products.endpoints.backend.tests.conftest import create_endpoint_with_version

SAMPLE_QUERY = {"kind": "HogQLQuery", "query": "SELECT 1"}
_UNSET = object()


def _make_psak(team, label="psak", scopes=_UNSET):
    # Token must match _SECRET_API_KEY_RE = r"^phs_[a-zA-Z0-9]+$", so only alphanumerics after phs_.
    suffix = "".join(c for c in label if c.isalnum())
    token = "phs_" + ("a" * 35) + suffix
    psak = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        mask_value=f"phs_...{suffix[:4]}",
        secure_value=hash_key_value(token),
        scopes=["endpoint:read"] if scopes is _UNSET else scopes,
    )
    return token, psak


class TestEndpointViewSetPSAKAuth(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint = create_endpoint_with_version(
            name="my_endpoint",
            team=self.team,
            query=SAMPLE_QUERY,
            created_by=self.user,
        )
        # Log out the test client so only the PSAK header authenticates requests
        self.client.logout()

    def _auth_headers(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_psak_can_run_endpoint(self):
        token, _ = _make_psak(self.team, label="run-key")

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_psak_can_run_endpoint_via_get(self):
        # `run` accepts both GET and POST; both resolve to the same action and must pass the
        # psak_allowed_actions gate.
        token, _ = _make_psak(self.team, label="get-key")

        response = self.client.get(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_psak_run_on_inactive_endpoint_returns_404(self):
        self.endpoint.is_active = False
        self.endpoint.save()
        token, _ = _make_psak(self.team, label="inactive-key")

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)

    def test_psak_run_skips_object_level_access_check(self):
        # PSAK scopes are project-wide by design: object-level access controls are only defined
        # for members/roles, which a synthetic principal has neither of, so run() must not
        # consult UserAccessControl at all for PSAK requests.
        token, _ = _make_psak(self.team, label="acl-skip-key")

        with patch.object(UserAccessControl, "specific_access_level_for_object") as acl_spy:
            response = self.client.post(
                f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
                data={},
                content_type="application/json",
                **self._auth_headers(token),
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        acl_spy.assert_not_called()

    def test_psak_run_updates_last_executed_at(self):
        # Freshness tracking gates on "any API-key access method", not just personal API keys —
        # a PSAK-only consumer must not look stale to the materialization-cleanup task.
        token, _ = _make_psak(self.team, label="freshness-key")
        self.assertIsNone(self.endpoint.last_executed_at)

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.endpoint.refresh_from_db()
        self.assertIsNotNone(self.endpoint.last_executed_at)
        version = self.endpoint.get_version()
        assert version is not None
        self.assertIsNotNone(version.last_executed_at)

    def test_psak_run_is_captured_with_synthetic_distinct_id(self):
        # report_user_action handles synthetic principals by capturing with their distinct_id —
        # otherwise key-driven traffic would be invisible to deprecation monitoring.
        token, psak = _make_psak(self.team, label="telemetry-key")

        with patch("posthog.event_usage.posthoganalytics.capture") as capture_mock:
            response = self.client.post(
                f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
                data={},
                content_type="application/json",
                **self._auth_headers(token),
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        executed_calls = [c for c in capture_mock.call_args_list if c.kwargs.get("event") == "endpoint executed"]
        self.assertEqual(len(executed_calls), 1)
        kwargs = executed_calls[0].kwargs
        self.assertEqual(kwargs["distinct_id"], f"psak-{self.team.id}-{psak.id}")
        self.assertEqual(kwargs["properties"]["auth_method"], "project_secret_api_key")
        self.assertEqual(kwargs["properties"]["endpoint_name"], "my_endpoint")
        self.assertEqual(kwargs["groups"]["project"], str(self.team.uuid))
        self.assertNotIn("$set_once", kwargs["properties"])

    def test_session_run_is_reported_as_user_action(self):
        # The user-auth path keeps the same event shape, captured under the real user's distinct_id.
        self.client.force_login(self.user)

        with patch("posthog.event_usage.posthoganalytics.capture") as capture_mock:
            response = self.client.post(
                f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
                data={},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        executed_calls = [c for c in capture_mock.call_args_list if c.kwargs.get("event") == "endpoint executed"]
        self.assertEqual(len(executed_calls), 1)
        kwargs = executed_calls[0].kwargs
        self.assertEqual(kwargs["distinct_id"], self.user.distinct_id)
        self.assertEqual(kwargs["properties"]["auth_method"], "user")
        self.assertEqual(kwargs["properties"]["endpoint_name"], "my_endpoint")

    def test_psak_in_body_is_not_accepted(self):
        token, _ = _make_psak(self.team, label="body-key")

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={"secret_api_key": token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.content)

    def test_psak_run_uses_synthetic_user_access_control(self):
        token, _ = _make_psak(self.team, label="run-with-rbac")

        captured: dict = {}

        def spy(team, user, user_access_control=None):
            result = _compute_system_table_access_decision(team, user, user_access_control)
            captured.setdefault("results", []).append(result)
            return result

        with patch("posthog.hogql.database.database._compute_system_table_access_decision", side_effect=spy):
            response = self.client.post(
                f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
                data={},
                content_type="application/json",
                **self._auth_headers(token),
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(captured.get("results"), "access-control decision was never exercised")
        for user_access_control, denied in captured["results"]:
            self.assertIsNone(user_access_control)
            self.assertNotIn("data_modeling_endpoints", denied)
            self.assertNotIn("data_modeling_endpoint_versions", denied)

    @parameterized.expand(
        [
            # PSAK must only authorize the `run` action — every other action returns 403.
            ("list", "GET", ""),
            ("retrieve", "GET", "my_endpoint/"),
            ("update", "PUT", "my_endpoint/"),
            ("partial_update", "PATCH", "my_endpoint/"),
            ("destroy", "DELETE", "my_endpoint/"),
            ("openapi_spec", "GET", "my_endpoint/openapi.json/"),
            ("materialization_status", "GET", "my_endpoint/materialization_status/"),
            ("materialization_preview", "POST", "my_endpoint/materialization_preview/"),
            ("versions", "GET", "my_endpoint/versions/"),
            ("last_execution_times", "POST", "last_execution_times/"),
        ]
    )
    def test_psak_blocked_on_non_run_actions(self, _name, method, path_suffix):
        token, _ = _make_psak(self.team, label=f"non-run-{_name}")

        response = self.client.generic(
            method,
            f"/api/projects/{self.team.id}/endpoints/{path_suffix}",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("does not support project secret API key", response.json().get("detail", ""))

    def test_psak_blocked_on_create(self):
        token, _ = _make_psak(self.team, label="create-key")

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/",
            data={"name": "new_endpoint", "query": SAMPLE_QUERY},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("does not support project secret API key", response.json().get("detail", ""))

    @parameterized.expand(
        [
            ("empty_list", []),
            ("null", None),
        ]
    )
    def test_psak_without_endpoint_scope_returns_403(self, _name, scopes):
        token, _ = _make_psak(self.team, label=f"no-scope-{_name}", scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("missing required scope 'endpoint:read'", response.json().get("detail", ""))

    def test_unknown_psak_returns_401(self):
        # Valid-looking but not-in-DB token
        response = self.client.post(
            f"/api/projects/{self.team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers("phs_" + "z" * 35),
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_psak_team_mismatch_returns_403(self):
        # PSAK belongs to team A; request targets team B.
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        token, _ = _make_psak(self.team, label="team-mismatch-key")

        response = self.client.post(
            f"/api/projects/{other_team.id}/endpoints/my_endpoint/run/",
            data={},
            content_type="application/json",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("does not have access to the requested project", response.json().get("detail", ""))

    def test_psak_without_feature_flag_read_scope_returns_403_on_remote_config(self):
        # remote_config accepts PSAK but requires feature_flag:read — endpoint-scoped keys must not pass.
        token, _ = _make_psak(self.team, label="remote-config-key")

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/some_flag/remote_config/",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("feature_flag:read", response.json().get("detail", ""))

    def test_session_auth_still_works_on_endpoint_viewset(self):
        # Regression: wiring PSAK into authentication_classes must not break session auth.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/endpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
@patch("products.endpoints.backend.rate_limit.EndpointBurstThrottle.rate", new="2/minute")
class TestEndpointPSAKRateLimit(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint = create_endpoint_with_version(
            name="rl_endpoint",
            team=self.team,
            query=SAMPLE_QUERY,
            created_by=self.user,
        )
        self.client.logout()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _run(self, token: str | None = None):
        url = f"/api/projects/{self.team.id}/endpoints/rl_endpoint/run/"
        if token is None:
            return self.client.post(url, data={}, content_type="application/json")
        return self.client.post(url, data={}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_psak_requests_are_throttled(self, *_args):
        token, _psak = _make_psak(self.team, label="rl-key")

        for _ in range(2):
            self.assertEqual(self._run(token).status_code, status.HTTP_200_OK)

        self.assertEqual(self._run(token).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_distinct_psak_keys_get_independent_buckets(self, *_args):
        token_a, _a = _make_psak(self.team, label="key-a")
        token_b, _b = _make_psak(self.team, label="key-b")

        for _ in range(2):
            self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_a).status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(self._run(token_b).status_code, status.HTTP_200_OK)

    @patch("products.endpoints.backend.rate_limit.EndpointProjectSecretApiKeyTeamBurstThrottle.rate", new="3/minute")
    def test_distinct_psak_keys_share_project_bucket(self, *_args):
        token_a, _a = _make_psak(self.team, label="team-key-a")
        token_b, _b = _make_psak(self.team, label="team-key-b")

        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_b).status_code, status.HTTP_200_OK)
        self.assertEqual(self._run(token_b).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_session_user_is_not_throttled(self, *_args):
        self.client.force_login(self.user)

        for _ in range(4):
            self.assertEqual(self._run().status_code, status.HTTP_200_OK)
