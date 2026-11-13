import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.test.authentication_checks import covers_authentication

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
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

CAPABILITY_CONTRACT = json.loads(
    (Path(__file__).parents[2] / "services/egress-proxy/internal/identity/testdata/python-capability.json").read_text()
)


@override_settings(
    AGENT_EGRESS_REGION="test-region", AGENT_EGRESS_REGISTRY_JWT_SECRETS=["test-egress-registry-key-000000000000"]
)
@time_machine.travel(CAPABILITY_CONTRACT["now"], tick=False)
class TestAgentEgressRegistrationAPI(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        registration = CAPABILITY_CONTRACT["registration"]
        self.client = APIClient()
        task = Task.objects.create(team=self.team, title="Synthetic egress task", created_by=self.user)
        self.task_run = TaskRun.objects.create(
            id=UUID(registration["run_id"]), task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS
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

    def test_child_environment_keeps_registration_and_capability_team(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        sibling = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        task = Task.objects.create(team=child, title="Child environment run", created_by=self.user)
        task_run = TaskRun.objects.create(task=task, team=child, status=TaskRun.Status.IN_PROGRESS)
        execution_id = uuid4()
        registration = self.registry.register(
            team_id=child.id,
            run_id=task_run.id,
            execution_id=execution_id,
            actor_id=self.user.id,
            authority="child-run.egress.example.com",
            relay_key_sha256=self.registration.relay_key_sha256,
        )
        url = f"/api/projects/{child.id}/internal/agent_egress/runs/{task_run.id}/executions/{execution_id}"
        response = self.client.get(
            url,
            headers=self._headers(team_id=child.id, sub=str(task_run.id), execution_id=str(execution_id)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team_id"], child.id)
        self.assertEqual(registration.team_id, child.id)

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
