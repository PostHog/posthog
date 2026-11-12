from typing import Any

from posthog.test.base import APIBaseTest

from django.contrib.admin import AdminSite
from django.test import RequestFactory, SimpleTestCase

from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.models.organization import Organization

from products.legal_documents.backend.admin import LegalDocumentAdmin, LegalDocumentInline
from products.legal_documents.backend.models import LegalDocument


class TestLegalDocumentAdminPermissions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = LegalDocumentAdmin(LegalDocument, AdminSite())
        self.request_factory = RequestFactory()

    def _request_for(self, *, is_staff: bool) -> Any:
        request = self.request_factory.get("/admin/posthog/legaldocument/")
        self.user.is_staff = is_staff
        self.user.save()
        request.user = self.user
        return request

    def test_staff_add_and_delete_only_in_the_console(self) -> None:
        request = self._request_for(is_staff=True)
        self.assertFalse(self.admin.has_add_permission(request))
        self.assertFalse(LegalDocumentInline(Organization, AdminSite()).has_add_permission(request, None))
        self.assertFalse(self.admin.has_delete_permission(request))
        self.assertNotIn("delete_selected", self.admin.get_actions(request))


class TestLegalDocumentInlineRegistration(SimpleTestCase):
    def test_inline_attaches_to_organization_admin(self) -> None:
        # legal_documents registers LegalDocumentInline via posthog.admin.inline_registry, so
        # core surfaces it on the Organization admin page without importing the product.
        org_admin = OrganizationAdmin(Organization, AdminSite())
        inlines = org_admin.get_inlines(RequestFactory().get("/"))
        self.assertIn(LegalDocumentInline, inlines)
        # It arrived through the registry, not core's static inlines list.
        self.assertNotIn(LegalDocumentInline, org_admin.inlines)
