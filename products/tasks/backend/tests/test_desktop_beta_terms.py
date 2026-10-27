from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.event_usage import groups
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team

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

    @patch("products.tasks.backend.presentation.views.desktop.posthoganalytics.capture")
    def test_admin_can_withdraw_terms_idempotently(self, capture) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.post(self.url)
        capture.reset_mock()

        first_response = self.client.post(f"{self.url}revoke/")
        second_response = self.client.post(f"{self.url}revoke/")

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertFalse(first_response.json()["is_desktop_beta_terms_accepted"])
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())
        self.assertFalse(self.client.get(self.url).json()["is_desktop_beta_terms_accepted"])
        capture.assert_called_once_with(
            distinct_id=self.user.distinct_id,
            event="desktop beta terms withdrawn",
            groups=groups(self.organization),
        )

    def test_member_cannot_withdraw_terms(self) -> None:
        DesktopBetaTermsAcceptance.objects.create(
            organization=self.organization,
            accepted_by_user_id=self.user.id,
        )

        response = self.client.post(f"{self.url}revoke/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(DesktopBetaTermsAcceptance.objects.filter(organization=self.organization).exists())

    def test_admin_cannot_accept_terms_for_another_organization(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        other_organization = Organization.objects.create(name="Other Organization")

        response = self.client.post(f"/api/organizations/{other_organization.id}/desktop_beta_terms/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.filter(organization=other_organization).exists())

    def _authenticate_with_project_scoped_token(self, scope: str = "organization:read organization:write") -> None:
        application = OAuthApplication.objects.create(
            name="PostHog Desktop",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8237/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_test_desktop_project_scoped_token",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
            scoped_organizations=[],
            scoped_teams=[self.team.id],
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")

    def test_project_scoped_oauth_token_can_check_and_accept_terms(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._authenticate_with_project_scoped_token()
        project_url = f"/api/projects/{self.team.id}/desktop_beta_terms/"

        check_response = self.client.get(project_url)
        accept_response = self.client.post(project_url)
        revoke_response = self.client.post(f"{project_url}revoke/")

        self.assertEqual(check_response.status_code, status.HTTP_200_OK)
        self.assertFalse(check_response.json()["is_desktop_beta_terms_accepted"])
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK, accept_response.json())
        self.assertTrue(accept_response.json()["is_desktop_beta_terms_accepted"])
        self.assertEqual(revoke_response.status_code, status.HTTP_200_OK, revoke_response.json())
        self.assertFalse(revoke_response.json()["is_desktop_beta_terms_accepted"])
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())

    def test_project_scoped_member_can_check_but_not_accept_terms(self) -> None:
        self._authenticate_with_project_scoped_token()
        project_url = f"/api/projects/{self.team.id}/desktop_beta_terms/"

        self.assertEqual(self.client.get(project_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(project_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())

    def test_project_scoped_read_only_token_cannot_accept_terms(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._authenticate_with_project_scoped_token(scope="organization:read")
        project_url = f"/api/projects/{self.team.id}/desktop_beta_terms/"

        self.assertEqual(self.client.get(project_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(project_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())

    def test_project_scoped_read_only_token_cannot_withdraw_terms(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        DesktopBetaTermsAcceptance.objects.create(
            organization=self.organization,
            accepted_by_user_id=self.user.id,
        )
        self._authenticate_with_project_scoped_token(scope="organization:read")
        project_url = f"/api/projects/{self.team.id}/desktop_beta_terms/"

        response = self.client.post(f"{project_url}revoke/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(DesktopBetaTermsAcceptance.objects.filter(organization=self.organization).exists())

    def test_project_scoped_token_cannot_access_another_project(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._authenticate_with_project_scoped_token()
        other_team = Team.objects.create(organization=self.organization)
        project_url = f"/api/projects/{other_team.id}/desktop_beta_terms/"

        self.assertEqual(self.client.get(project_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(project_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(DesktopBetaTermsAcceptance.objects.exists())
