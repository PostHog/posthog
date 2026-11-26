import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.redis import TEST_clear_clients
from posthog.test.authentication_checks import covers_authentication
from posthog.token_bucket import TEST_reset_scripts

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_git import AgentEgressGitGrants, GitReadCredential
from products.tasks.backend.logic.services.connection_token import (
    AGENT_EGRESS_AUDIENCE,
    AGENT_EGRESS_ISSUER,
    reset_sandbox_jwt_key_cache,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.presentation.views.agent_egress import (
    AGENT_EGRESS_REGISTRY_PURPOSE,
    AgentEgressRegistryAuthentication,
)
from products.tasks.backend.presentation.views.agent_egress_git import (
    AGENT_EGRESS_CREDENTIALS_PURPOSE,
    AgentEgressCredentialsAuthentication,
)

CAPABILITY_CONTRACT = json.loads(
    (Path(__file__).parents[2] / "services/egress-proxy/internal/identity/testdata/python-capability.json").read_text()
)
GIT_GRANT_CONTRACT = json.loads(
    (Path(__file__).parents[2] / "services/egress-proxy/internal/gitread/testdata/grant.json").read_text()
)


@override_settings(
    AGENT_EGRESS_REGION="test-region",
    AGENT_EGRESS_REGISTRY_JWT_SECRETS=["test-egress-registry-key-000000000000"],
    AGENT_EGRESS_CREDENTIALS_JWT_SECRETS=["test-egress-credentials-key-0000000000"],
)
@time_machine.travel(CAPABILITY_CONTRACT["now"], tick=False)
class TestAgentEgressRegistrationAPI(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)
        registration = CAPABILITY_CONTRACT["registration"]
        self.client = APIClient()
        task = Task.objects.create(team=self.team, title="Synthetic egress task", created_by=self.user)
        self.task_run = TaskRun.objects.create(
            id=UUID(registration["run_id"]),
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-api", "sandbox_backend": "modal"},
        )
        self.execution_id = UUID(registration["execution_id"])
        self.registry = AgentEgressRegistry(region=registration["region"])
        self.registration = self.registry.register(
            team_id=self.team.id,
            run_id=self.task_run.id,
            execution_id=self.execution_id,
            actor_id=self.user.id,
            authority=registration["authority"],
            relay_key_sha256=registration["relay_key_sha256"],
            sandbox_id="sb-api",
        )
        self.url = (
            f"/api/projects/{self.team.id}/internal/agent_egress/runs/{self.task_run.id}/executions/{self.execution_id}"
        )

    def _headers(self, **overrides: object) -> dict[str, str]:
        claims = {
            "team_id": self.team.id,
            "sub": str(self.task_run.id),
            "execution_id": str(self.execution_id),
            "region": "test-region",
            "operation": "lookup",
            "iat": int(timezone.now().timestamp()),
            **overrides,
        }
        if claims.get("iat") is None:
            del claims["iat"]
        return {"Authorization": f"Bearer {AGENT_EGRESS_REGISTRY_PURPOSE.mint(claims)}"}

    def _git_headers(self, **overrides: object) -> dict[str, str]:
        return {
            "Authorization": "Bearer "
            + AGENT_EGRESS_CREDENTIALS_PURPOSE.mint(
                {
                    "team_id": self.team.id,
                    "sub": str(self.task_run.id),
                    "execution_id": str(self.execution_id),
                    "region": "test-region",
                    "operation": "git_read_grant",
                    "repository": GIT_GRANT_CONTRACT["repository"],
                    "iat": int(timezone.now().timestamp()),
                    **overrides,
                }
            )
        }

    def _publish_git_grant(self) -> None:
        AgentEgressGitGrants(region="test-region").publish(
            team_id=self.team.id,
            run_id=self.task_run.id,
            execution_id=self.execution_id,
            credential=GitReadCredential(
                repository=GIT_GRANT_CONTRACT["repository"],
                token=GIT_GRANT_CONTRACT["token"],
                expires_at=GIT_GRANT_CONTRACT["expires_at"],
            ),
            version=UUID(GIT_GRANT_CONTRACT["credential_version"]),
            previous_version=None,
        )

    @covers_authentication(AgentEgressCredentialsAuthentication)
    def test_git_grant_matches_go_contract_and_stays_out_of_registration_lookup(self) -> None:
        self._publish_git_grant()
        response = self.client.get(
            self.url + "/git_read_grant/",
            headers=self._git_headers(),
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(
            response.json(),
            {
                **GIT_GRANT_CONTRACT,
                "registration": {
                    **GIT_GRANT_CONTRACT["registration"],
                    "team_id": self.team.id,
                    "actor_id": self.user.id,
                },
            },
        )
        metadata = self.client.get(self.url, headers=self._headers()).json()
        self.assertNotIn(GIT_GRANT_CONTRACT["token"], str(metadata))
        self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        self.assertEqual(
            self.client.get(
                self.url + "/git_read_grant/",
                headers=self._git_headers(),
                secure=True,
            ).status_code,
            404,
        )

    @parameterized.expand(
        [
            ("sub", "00000000-0000-0000-0000-000000000001", 403),
            ("execution_id", "00000000-0000-0000-0000-000000000002", 403),
            ("region", "other-region", 403),
            ("operation", "lookup", 403),
            ("repository", "example/other", 404),
            ("repository", None, 403),
            ("iat", None, 401),
            ("iat", 0, 403),
        ]
    )
    def test_git_grant_auth_pins_scope(self, claim: str, value: object, expected: int) -> None:
        self._publish_git_grant()
        response = self.client.get(
            self.url + "/git_read_grant/",
            headers=self._git_headers(**{claim: value}),
            secure=True,
        )
        self.assertEqual(response.status_code, expected)
        self.assertNotIn(GIT_GRANT_CONTRACT["token"], response.content.decode())

    @parameterized.expand([("127.0.0.1", 200), ("::1", 200), ("10.0.0.2", 403), ("", 403)])
    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), TRUST_ALL_PROXIES=True)
    def test_git_grant_requires_local_tls_transport(self, peer: str, expected: int) -> None:
        self._publish_git_grant()
        response = self.client.get(
            self.url + "/git_read_grant/",
            headers={
                **self._git_headers(),
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
                "Forwarded": "for=127.0.0.1;proto=https",
            },
            REMOTE_ADDR=peer,
        )
        self.assertEqual(response.status_code, expected, response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        if expected != 200:
            self.assertNotIn(GIT_GRANT_CONTRACT["token"], response.content.decode())

    def test_git_grant_requires_separate_key_https_and_available_registry(self) -> None:
        self._publish_git_grant()
        url = self.url + "/git_read_grant/"
        self.assertEqual(self.client.get(url, headers=self._headers(), secure=True).status_code, 401)
        self.assertEqual(self.client.get(url, headers=self._git_headers()).status_code, 503)
        self.assertEqual(
            self.client.get(url, headers=self._git_headers(team_id=self.team.id + 1), secure=True).status_code, 401
        )
        with self.settings(AGENT_EGRESS_CREDENTIALS_JWT_SECRETS=[]):
            self.assertEqual(self.client.get(url, headers=self._headers(), secure=True).status_code, 401)
        with (
            patch(
                "products.tasks.backend.logic.services.agent_egress_git.AgentEgressRegistry.lookup",
                side_effect=OperationalError(GIT_GRANT_CONTRACT["token"]),
            ),
            self.assertLogs("products.tasks.backend.presentation.views.agent_egress_git", level="WARNING") as logs,
        ):
            response = self.client.get(url, headers=self._git_headers(), secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "no-store")
        record = logs.records[0]
        self.assertEqual(record.getMessage(), "agent_egress_git_grant_unavailable")
        self.assertEqual(
            {key: record.__dict__[key] for key in ("error_type", "team_id", "run_id", "execution_id")},
            {
                "error_type": "OperationalError",
                "team_id": self.team.id,
                "run_id": str(self.task_run.id),
                "execution_id": str(self.execution_id),
            },
        )
        self.assertIsNone(record.exc_info)
        self.assertNotIn(GIT_GRANT_CONTRACT["token"], repr(record.__dict__))

    def test_git_grant_budget_survives_token_rotation_and_isolates_executions_and_teams(self) -> None:
        self._publish_git_grant()
        url = self.url + "/git_read_grant/"
        headers = self._git_headers()
        for _ in range(60):
            self.assertEqual(self.client.get(url, headers=headers, secure=True).status_code, 200)

        for request_headers in (headers, self._git_headers(jti=str(uuid4()))):
            response = self.client.get(url, headers=request_headers, secure=True)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response["Retry-After"], "6")
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertNotIn(GIT_GRANT_CONTRACT["token"], response.content.decode())

        other_execution = str(uuid4())
        response = self.client.get(
            url.replace(str(self.execution_id), other_execution),
            headers=self._git_headers(execution_id=other_execution),
            secure=True,
        )
        self.assertEqual(response.status_code, 404)
        other_team = Team.objects.create(organization=self.organization)
        response = self.client.get(
            url.replace(f"/projects/{self.team.id}/", f"/projects/{other_team.id}/"),
            headers=self._git_headers(team_id=other_team.id),
            secure=True,
        )
        self.assertEqual(response.status_code, 404)

        with time_machine.travel(timezone.now() + timedelta(seconds=6), tick=False):
            self.assertEqual(self.client.get(url, headers=headers, secure=True).status_code, 200)
            self.assertEqual(self.client.get(url, headers=headers, secure=True).status_code, 429)

    def test_git_grant_denies_lookup_when_rate_limit_store_is_unavailable(self) -> None:
        self._publish_git_grant()
        broken = MagicMock()
        broken.register_script.return_value.side_effect = RedisConnectionError("unavailable")
        with patch("posthog.token_bucket.get_client", return_value=broken):
            response = self.client.get(self.url + "/git_read_grant/", headers=self._git_headers(), secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn(GIT_GRANT_CONTRACT["token"], response.content.decode())

    @covers_authentication(AgentEgressRegistryAuthentication)
    def test_lookup_returns_only_current_registration(self) -> None:
        response = self.client.get(self.url, headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(
            response.json(),
            {
                **CAPABILITY_CONTRACT["registration"],
                "team_id": self.team.id,
                "actor_id": self.user.id,
            },
        )

        self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        self.assertEqual(self.client.get(self.url, headers=self._headers()).status_code, 404)

    @parameterized.expand(
        [
            ("run", "sub", "00000000-0000-0000-0000-000000000001"),
            ("execution", "execution_id", "00000000-0000-0000-0000-000000000002"),
            ("region", "region", "other-region"),
            ("operation", "operation", "register"),
            ("stale_issue_time", "iat", 0),
            ("missing_issue_time", "iat", None),
        ]
    )
    def test_refuses_other_authority(self, _name: str, claim: str, value: object) -> None:
        self.assertEqual(self.client.get(self.url, headers=self._headers(**{claim: value})).status_code, 403)

    def test_refuses_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self.assertEqual(self.client.get(self.url, headers=self._headers(team_id=other_team.id)).status_code, 401)

    def test_lookup_refuses_a_registration_after_the_sandbox_changes(self) -> None:
        TaskRun.update_state_atomic(self.task_run.id, updates={"sandbox_id": "sb-replacement"})
        response = self.client.get(self.url, headers=self._headers())
        self.assertEqual(response.status_code, 404)

    def test_child_environment_keeps_registration_and_capability_team(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        sibling = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        task = Task.objects.create(team=child, title="Child environment run", created_by=self.user)
        task_run = TaskRun.objects.create(
            task=task,
            team=child,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-child", "sandbox_backend": "modal"},
        )
        execution_id = uuid4()
        registration = self.registry.register(
            team_id=child.id,
            run_id=task_run.id,
            execution_id=execution_id,
            actor_id=self.user.id,
            authority="child-run.egress.example.com",
            relay_key_sha256=self.registration.relay_key_sha256,
            sandbox_id="sb-child",
        )
        url = f"/api/projects/{child.id}/internal/agent_egress/runs/{task_run.id}/executions/{execution_id}"
        response = self.client.get(
            url,
            headers=self._headers(team_id=child.id, sub=str(task_run.id), execution_id=str(execution_id)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team_id"], child.id)
        self.assertEqual(registration.team_id, child.id)

        AgentEgressGitGrants(region="test-region").publish(
            team_id=child.id,
            run_id=task_run.id,
            execution_id=execution_id,
            credential=GitReadCredential(
                repository=GIT_GRANT_CONTRACT["repository"],
                token=GIT_GRANT_CONTRACT["token"],
                expires_at=GIT_GRANT_CONTRACT["expires_at"],
            ),
            version=uuid4(),
            previous_version=None,
        )
        response = self.client.get(
            url + "/git_read_grant/",
            headers=self._git_headers(team_id=child.id, sub=str(task_run.id), execution_id=str(execution_id)),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registration"]["team_id"], child.id)

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        with override_settings(SANDBOX_JWT_PRIVATE_KEY=pem, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None):
            reset_sandbox_jwt_key_cache()
            self.addCleanup(reset_sandbox_jwt_key_cache)
            token = self.registry.issue_capability(team_id=child.id, run_id=task_run.id, execution_id=execution_id)
            claims = jwt.decode(
                token,
                key.public_key(),
                algorithms=["RS256"],
                audience=AGENT_EGRESS_AUDIENCE,
                issuer=AGENT_EGRESS_ISSUER,
            )
            self.assertEqual(claims["team_id"], child.id)

        for denied_team in (self.team, sibling):
            denied_url = (
                f"/api/projects/{denied_team.id}/internal/agent_egress/runs/{task_run.id}/executions/{execution_id}"
            )
            response = self.client.get(
                denied_url,
                headers=self._headers(team_id=denied_team.id, sub=str(task_run.id), execution_id=str(execution_id)),
            )
            self.assertEqual(response.status_code, 404)

            response = self.client.get(
                denied_url + "/git_read_grant/",
                headers=self._git_headers(team_id=denied_team.id, sub=str(task_run.id), execution_id=str(execution_id)),
                secure=True,
            )
            self.assertEqual(response.status_code, 404)

    @parameterized.expand([("expired", -1), ("too_long", 31)])
    def test_refuses_invalid_service_lifetime(self, _name: str, lifetime: int) -> None:
        claims = {
            "team_id": self.team.id,
            "sub": str(self.task_run.id),
            "execution_id": str(self.execution_id),
            "operation": "lookup",
            "region": "test-region",
            "iat": int(timezone.now().timestamp()),
        }
        token = AGENT_EGRESS_REGISTRY_PURPOSE.mint(claims, ttl=timedelta(seconds=lifetime))
        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 401 if lifetime < 0 else 403)

    @parameterized.expand([("missing", None), ("guest_audience", "posthog:agent_egress")])
    def test_refuses_missing_or_guest_auth(self, _name: str, audience: str | None) -> None:
        headers = {}
        if audience:
            token = jwt.encode(
                {"team_id": self.team.id, "aud": audience, "exp": timezone.now() + timedelta(seconds=30)},
                "test-egress-registry-key-000000000000",
                algorithm="HS256",
            )
            headers["Authorization"] = f"Bearer {token}"
        self.assertEqual(self.client.get(self.url, headers=headers).status_code, 401)

    def test_service_key_rotation_accepts_overlap_then_retires_old_key(self) -> None:
        headers = self._headers()
        with self.settings(
            AGENT_EGRESS_REGISTRY_JWT_SECRETS=[
                "new-test-egress-key-0000000000000000",
                "test-egress-registry-key-000000000000",
            ]
        ):
            self.assertEqual(self.client.get(self.url, headers=headers).status_code, 200)
        with self.settings(AGENT_EGRESS_REGISTRY_JWT_SECRETS=["new-test-egress-key-0000000000000000"]):
            self.assertEqual(self.client.get(self.url, headers=headers).status_code, 401)

    def test_has_no_registration_write_route(self) -> None:
        self.assertEqual(self.client.post(self.url, {}, headers=self._headers()).status_code, 405)

    @parameterized.expand([("missing", ""), ("invalid", "invalid region"), ("too_long", "a" * 33)])
    def test_invalid_region_does_not_serve_registration(self, _name: str, region: str) -> None:
        with override_settings(AGENT_EGRESS_REGION=region):
            self.assertEqual(self.client.get(self.url, headers=self._headers(region=region)).status_code, 503)
