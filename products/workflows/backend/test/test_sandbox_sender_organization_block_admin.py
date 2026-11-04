from posthog.test.base import BaseTest

from django.test import Client, override_settings

from products.workflows.backend.models import SandboxSenderOrganizationBlock

ADMIN_URL = "/admin/workflows/sandboxsenderorganizationblock/"


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestSandboxSenderOrganizationBlockAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.organization.name = "Blocked example organization"
        self.organization.save()
        self.client = Client()
        self.client.force_login(self.user)

    def test_staff_add_a_block_with_its_author_and_delete_it(self) -> None:
        added = self.client.post(
            f"{ADMIN_URL}add/", data={"organization": str(self.organization.id), "reason": "Abuse report"}
        )

        assert added.status_code == 302, added.content
        block = SandboxSenderOrganizationBlock.objects.get(organization=self.organization)
        assert (block.reason, block.created_by) == ("Abuse report", self.user)

        confirmation = self.client.get(f"{ADMIN_URL}{block.pk}/delete/")
        assert self.organization.name in confirmation.content.decode()

        deleted = self.client.post(f"{ADMIN_URL}{block.pk}/delete/", data={"post": "yes"})

        assert deleted.status_code == 302, deleted.content
        assert not SandboxSenderOrganizationBlock.objects.filter(organization=self.organization).exists()
