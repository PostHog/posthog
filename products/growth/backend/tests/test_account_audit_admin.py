import base64
from uuid import uuid4

from posthog.test.base import BaseTest

from django.contrib.admin.models import LogEntry
from django.urls import reverse

from parameterized import parameterized

from products.growth.backend.admin import AccountAuditCredentialForm
from products.growth.backend.models import AccountAuditCredential


class TestAccountAuditCredentialAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        self.add_url = reverse("admin:growth_accountauditcredential_add")
        self.add_data = {"owner": self.user.pk, "workflow_id": "", "is_active": "on"}

    @parameterized.expand([("us", "https://us.posthog.com", False), ("eu", "https://eu.posthog.com", True)])
    def test_admin_provisions_once_then_allows_overlap_and_revocation_without_exposing_secret(
        self, _region: str, site_url: str, workflow_reference: bool
    ) -> None:
        self.enterContext(self.settings(SITE_URL=site_url))
        workflow_id = uuid4() if workflow_reference else None
        self.add_data["workflow_id"] = str(workflow_id) if workflow_id else ""
        response = self.client.post(self.add_url, self.add_data)
        self.assertEqual(response.status_code, 200)
        credential = AccountAuditCredential.objects.get()
        secret = credential.signing_secret
        self.assertTrue(secret.startswith("whsec_"))
        self.assertEqual(len(base64.b64decode(secret.removeprefix("whsec_"))), 32)
        self.assertContains(response, secret)
        self.assertContains(response, f"{site_url}{reverse('growth_account_audits-start')}")
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

        response = self.client.post(
            change_url, {"owner": "", "workflow_id": str(uuid4()), "signing_secret": "replacement"}
        )
        self.assertEqual(response.status_code, 302)
        credential.refresh_from_db()
        self.assertFalse(credential.is_active)
        self.assertEqual(credential.owner_id, self.user.pk)
        self.assertEqual(credential.workflow_id, workflow_id)
        self.assertEqual(credential.signing_secret, secret)
        replacement.refresh_from_db()
        self.assertTrue(replacement.is_active)

    @parameterized.expand([("is_staff",), ("is_active",)])
    def test_admin_cannot_reactivate_a_credential_for_an_ineligible_owner(self, field: str) -> None:
        credential = AccountAuditCredential.objects.create(owner=self.user, signing_secret="unused", is_active=False)
        setattr(self.user, field, False)
        self.user.save(update_fields=[field])
        form = AccountAuditCredentialForm(instance=credential, data=self.add_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Choose an active staff user", str(form.errors))
