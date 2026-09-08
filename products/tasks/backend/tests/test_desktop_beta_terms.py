from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership

from products.tasks.backend.models import DesktopBetaTermsAcceptance


class TestDesktopBetaTermsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/organizations/{self.organization.id}/desktop_beta_terms/"

    def test_admin_can_accept_terms_idempotently(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        first_response = self.client.post(self.url)
        second_response = self.client.post(self.url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(DesktopBetaTermsAcceptance.objects.filter(organization=self.organization).count(), 1)
        self.assertTrue(self.client.get(self.url).json()["is_desktop_beta_terms_accepted"])

    def test_member_can_check_but_not_accept_terms(self) -> None:
        check_response = self.client.get(self.url)
        accept_response = self.client.post(self.url)

        self.assertEqual(check_response.status_code, status.HTTP_200_OK)
        self.assertFalse(check_response.json()["is_desktop_beta_terms_accepted"])
        self.assertEqual(accept_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())

    def test_admin_cannot_accept_terms_for_another_organization(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        other_organization = Organization.objects.create(name="Other Organization")

        response = self.client.post(f"/api/organizations/{other_organization.id}/desktop_beta_terms/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.filter(organization=other_organization).exists())
