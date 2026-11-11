from collections.abc import Callable
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import Client, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.facade.sandbox_email import SANDBOX_SENDER_ADOPTION_FLAG, provision_sandbox_sender
from products.workflows.backend.models import SandboxSenderOrganizationBlock
from products.workflows.backend.tests.fakes.ses_endpoint import FakeSesEndpoint


def _flag(enabled: bool):
    return patch(
        "posthoganalytics.feature_enabled",
        side_effect=lambda key, *_args, **_kwargs: enabled and key == SANDBOX_SENDER_ADOPTION_FLAG,
    )


def _sandbox_rows(team_id: int) -> list[Integration]:
    return list(Integration.objects.filter(team_id=team_id, kind="email_sandbox"))


@override_settings(SES_SANDBOX_FROM_ADDRESS="sandbox@example.com")
class TestWorkflowEmailSandbox(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/workflow_email_sandbox/{action}/"

    @parameterized.expand([("flag_off", False, False), ("organization_blocked", True, True)])
    def test_provision_refuses_when_the_organization_cannot_adopt(
        self, _name: str, enabled: bool, blocked: bool
    ) -> None:
        if blocked:
            SandboxSenderOrganizationBlock.objects.create(organization=self.organization, reason="abuse")

        with _flag(enabled):
            response = self.client.post(self._url("provision"))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert _sandbox_rows(self.team.id) == []

    def test_provision_creates_one_row_without_calling_the_email_provider(self) -> None:
        with _flag(True), FakeSesEndpoint().installed() as ses:
            first = self.client.post(self._url("provision"))
            second = self.client.post(self._url("provision"))

        assert [first.status_code, second.status_code] == [status.HTTP_200_OK, status.HTTP_200_OK], first.json()
        rows = _sandbox_rows(self.team.id)
        assert [row.id for row in rows] == [first.json()["integration_id"]] == [second.json()["integration_id"]]
        assert rows[0].integration_id == "posthog-managed-sandbox"
        assert rows[0].config == {}
        assert rows[0].created_by_id == self.user.id
        assert ses.requests == []

    def test_provision_reuses_a_row_another_request_created(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "testtest")
        existing = Integration.objects.create(
            team=self.team,
            kind="email_sandbox",
            integration_id="posthog-managed-sandbox",
            config={},
            created_by=other_user,
        )

        with _flag(True):
            response = self.client.post(self._url("provision"))

        assert response.json() == {"integration_id": existing.id}
        assert [row.created_by_id for row in _sandbox_rows(self.team.id)] == [other_user.id]

    def test_provision_keeps_the_creator_of_a_row_committed_after_its_lookup(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "testtest")
        competing: list[Integration] = []
        raced: list[bool] = []

        def commit_competing_row_after_lookup(
            execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any
        ) -> Any:
            result = execute(sql, params, many, context)
            if not raced and sql.lstrip().upper().startswith("SELECT") and '"posthog_integration"' in sql:
                raced.append(True)
                competing.append(
                    Integration.objects.create(
                        team=self.team,
                        kind="email_sandbox",
                        integration_id="posthog-managed-sandbox",
                        config={},
                        created_by=other_user,
                    )
                )
            return result

        with connection.execute_wrapper(commit_competing_row_after_lookup):
            row = provision_sandbox_sender(self.team, self.user)

        assert row.id == competing[0].id
        assert [stored.created_by_id for stored in _sandbox_rows(self.team.id)] == [other_user.id]

    @parameterized.expand([("before_provision", False), ("after_provision", True)])
    def test_status_describes_the_sender(self, _name: str, provisioned: bool) -> None:
        self.organization.name = "Acme"
        self.organization.save()
        row = (
            Integration.objects.create(
                team=self.team, kind="email_sandbox", integration_id="posthog-managed-sandbox", config={}
            )
            if provisioned
            else None
        )

        with _flag(True):
            response = self.client.get(self._url("status"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "integration_id": row.id if row else None,
            "from_address": "sandbox@example.com",
            "display_name": "Acme via PostHog",
            "organization_blocked": False,
            "adoption_enabled": True,
        }

    def test_generic_integration_endpoints_refuse_the_sandbox_kind(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        sandbox_row = Integration.objects.create(
            team=self.team, kind="email_sandbox", integration_id="posthog-managed-sandbox", config={}
        )
        base = f"/api/environments/{self.team.id}/integrations"

        created = self.client.post(f"{base}/", {"kind": "email_sandbox", "config": {}}, format="json")
        verified = self.client.post(f"{base}/{sandbox_row.id}/email/verify/")
        updated = self.client.patch(f"{base}/{sandbox_row.id}/email/", {"config": {}}, format="json")

        assert [created.status_code, verified.status_code, updated.status_code] == [400, 400, 400]
        assert _sandbox_rows(self.team.id) == [sandbox_row]

    @parameterized.expand([("own",), ("forged",), ("omitted",)])
    @override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_admin_records_who_blocked_the_organization(self, posted_creator: str) -> None:
        self.user.is_staff = True
        self.user.save()
        other_staff = User.objects.create_and_join(self.organization, "other-staff@example.com", None)
        created_by = {
            "own": {"created_by": self.user.pk},
            "forged": {"created_by": other_staff.pk},
            "omitted": {},
        }[posted_creator]
        admin_client = Client()
        admin_client.force_login(self.user)

        response = admin_client.post(
            "/admin/workflows/sandboxsenderorganizationblock/add/",
            {"organization": self.organization.pk, "reason": "abuse", **created_by},
        )

        assert response.status_code == 302, response.content
        assert SandboxSenderOrganizationBlock.objects.get(organization=self.organization).created_by == self.user


@pytest.mark.ee
class TestWorkflowEmailSandboxAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        AccessControl.objects.create(team=self.team, resource="hog_flow", resource_id=None, access_level="none")

    def _member_with(self, access_level: str) -> User:
        user = User.objects.create_and_join(self.organization, f"{access_level}@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=None,
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )
        return user

    @parameterized.expand([("viewer", 403), ("editor", 200)])
    def test_status_and_provision_need_workflow_write_access(self, access_level: str, expected: int) -> None:
        self.client.force_login(self._member_with(access_level))
        base = f"/api/projects/{self.team.id}/workflow_email_sandbox"

        with _flag(True):
            responses = [self.client.get(f"{base}/status/"), self.client.post(f"{base}/provision/")]

        assert [response.status_code for response in responses] == [expected, expected]
