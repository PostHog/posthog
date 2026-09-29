import base64
from uuid import uuid4

from posthog.test.base import BaseTest

from django.contrib.admin.models import LogEntry
from django.urls import reverse

from products.growth.backend.admin import AccountAuditCredentialForm
from products.growth.backend.models import AccountAuditCredential
from products.workflows.backend.models import HogFlow


class TestAccountAuditCredentialAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        self.flow = HogFlow.objects.create(team=self.team, created_by=self.user, status=HogFlow.State.ACTIVE)
        self.add_url = reverse("admin:growth_accountauditcredential_add")
        self.add_data = {"owner": self.user.pk, "workflow_id": str(self.flow.pk), "is_active": "on"}
        self.enterContext(self.settings(GROWTH_ENRICHMENT_INTERNAL_TEAM_ID=self.team.pk))

    def test_admin_provisions_once_then_allows_overlap_and_revocation_without_exposing_secret(self) -> None:
        response = self.client.post(self.add_url, self.add_data)
        self.assertEqual(response.status_code, 200)
        credential = AccountAuditCredential.objects.get()
        secret = credential.signing_secret
        self.assertTrue(secret.startswith("whsec_"))
        self.assertEqual(len(base64.b64decode(secret.removeprefix("whsec_"))), 32)
        self.assertContains(response, secret)
        self.assertIn("no-store", response.headers["Cache-Control"])
        change_url = reverse("admin:growth_accountauditcredential_change", args=[credential.pk])
        self.assertNotContains(self.client.get(change_url), secret)
        self.assertNotContains(self.client.get(reverse("admin:growth_accountauditcredential_changelist")), secret)
        self.assertFalse(LogEntry.objects.filter(change_message__contains=secret).exists())

        response = self.client.post(self.add_url, self.add_data)
        self.assertEqual(response.status_code, 200)
        replacement = AccountAuditCredential.objects.exclude(pk=credential.pk).get()
        self.assertNotEqual(replacement.signing_secret, secret)
        credential.refresh_from_db()
        self.assertTrue(credential.is_active)

        self.flow.status = HogFlow.State.ARCHIVED
        self.flow.save(update_fields=["status"])
        response = self.client.post(
            change_url, {"owner": "", "workflow_id": str(uuid4()), "signing_secret": "replacement"}
        )
        self.assertEqual(response.status_code, 302)
        credential.refresh_from_db()
        self.assertFalse(credential.is_active)
        self.assertEqual(credential.owner_id, self.user.pk)
        self.assertEqual(credential.workflow_id, self.flow.pk)
        self.assertEqual(credential.signing_secret, secret)
        replacement.refresh_from_db()
        self.assertTrue(replacement.is_active)

    def test_admin_rejects_a_workflow_outside_the_growth_project(self) -> None:
        with self.settings(GROWTH_ENRICHMENT_INTERNAL_TEAM_ID=self.team.pk + 1):
            response = self.client.post(self.add_url, self.add_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose an active Workflow")
        self.assertFalse(AccountAuditCredential.objects.exists())

    def test_admin_cannot_reactivate_a_credential_for_an_ineligible_owner(self) -> None:
        credential = AccountAuditCredential.objects.create(
            owner=self.user, workflow_id=self.flow.pk, signing_secret="unused", is_active=False
        )
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        form = AccountAuditCredentialForm(instance=credential, data=self.add_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Choose an active Workflow", str(form.errors))
