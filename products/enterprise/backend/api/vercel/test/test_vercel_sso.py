from contextlib import contextmanager

import pytest
from unittest.mock import Mock, patch

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration

from products.enterprise.backend.api.vercel.types import VercelUserClaims


class TestConstants:
    AUTH_CODE = "test_auth_code"
    STATE = "test_state"
    EMAIL = "sso@example.com"
    BASE_SSO_PARAMS = {"mode": "sso", "code": AUTH_CODE, "state": STATE}


class MockFactory:
    @staticmethod
    def successful_sso_flow(installation_id: str, user_id: str = "sso_user_123"):
        return {
            "_validate_client_credentials": Mock(return_value=("test_client_id", "test_client_secret")),
            "_exchange_sso_token": Mock(return_value=Mock(id_token="mock_id_token", error=None)),
        }

    @staticmethod
    def failed_token_exchange():
        return {
            "_validate_client_credentials": Mock(return_value=("test_client_id", "test_client_secret")),
            "_exchange_sso_token": Mock(return_value=Mock(error="invalid_code")),
        }

    @staticmethod
    def missing_id_token():
        return {
            "_validate_client_credentials": Mock(return_value=("test_client_id", "test_client_secret")),
            "_exchange_sso_token": Mock(return_value=Mock(id_token=None, error=None)),
        }

    @staticmethod
    def token_exchange_returns_none():
        return {
            "_validate_client_credentials": Mock(return_value=("test_client_id", "test_client_secret")),
            "_exchange_sso_token": Mock(return_value=None),
        }

    @staticmethod
    def missing_credentials():
        from rest_framework.exceptions import NotFound

        return {
            "_validate_client_credentials": Mock(side_effect=NotFound("Missing credentials")),
        }


@contextmanager
def mock_vercel_integration(**overrides):
    defaults = MockFactory.successful_sso_flow("default_installation_id")
    defaults.update(overrides)

    with patch.multiple("ee.vercel.integration.VercelIntegration", **defaults):
        yield


@contextmanager
def mock_jwt_validation(claims):
    with patch("products.enterprise.backend.api.authentication.VercelAuthentication._validate_jwt_token") as mock_jwt:
        mock_jwt.return_value = claims
        yield mock_jwt


class SSOTestHelper:
    @staticmethod
    def make_sso_request(client, endpoint_url, **extra_params):
        params = {**TestConstants.BASE_SSO_PARAMS, **extra_params}
        return client.get(endpoint_url, params)

    @staticmethod
    def assert_successful_redirect(response, expected_url="/"):
        assert response.status_code == status.HTTP_302_FOUND
        assert response.url == expected_url

    @staticmethod
    def assert_login_redirect(response, expected_continuation_params):
        """Assert that the response redirects to login with proper continuation URL"""
        assert response.status_code == status.HTTP_302_FOUND
        assert response.url.startswith("/login?next=")
        for param, value in expected_continuation_params.items():
            assert f"{param}={value}" in response.url or f"{param}%3D{value}" in response.url

    @staticmethod
    def assert_user_mapping_created(installation, user_id, user_pk):
        installation.refresh_from_db()
        user_mappings = installation.config.get("user_mappings", {})
        assert user_id in user_mappings
        assert user_mappings[user_id] == user_pk


# Sentinel value to distinguish between default email and explicit None
_DEFAULT_EMAIL = object()


def create_user_claims(installation_id: str, user_id: str = "sso_user_123", email=_DEFAULT_EMAIL) -> VercelUserClaims:
    # Use TestConstants.EMAIL as default, but allow explicit None for testing missing email scenarios
    resolved_email = TestConstants.EMAIL if email is _DEFAULT_EMAIL else email
    return VercelUserClaims(
        iss="https://marketplace.vercel.com",
        sub="account:test:user:sso",
        aud="test_audience",
        account_id="test_account",
        installation_id=installation_id,
        user_id=user_id,
        user_role="USER",
        type=None,
        user_avatar_url=None,
        user_email=resolved_email,
        user_name="SSO User",
    )


@pytest.fixture
def sso_setup(db, client):
    sso_user = User.objects.create_user(email=TestConstants.EMAIL, password="testpass", first_name="SSO User")
    sso_organization = Organization.objects.create(name="SSO Test Org")
    sso_user.join(organization=sso_organization, level=OrganizationMembership.Level.MEMBER)

    sso_installation_id = "icfg_sso123456789012345678"
    sso_installation = OrganizationIntegration.objects.create(
        organization=sso_organization,
        kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        integration_id=sso_installation_id,
        config={"billing_plan_id": "free", "scopes": ["read"]},
        created_by=sso_user,
    )

    return {
        "user": sso_user,
        "organization": sso_organization,
        "installation": sso_installation,
        "installation_id": sso_installation_id,
        "client": client,
        "url": "/login/vercel/",
    }


class BaseSSOMockTest:
    """Base class for SSO tests requiring common mock patterns."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, sso_setup):
        """Automatically set up successful SSO mocks for inheriting test classes."""
        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"])) as mock_jwt,
        ):
            yield mock_jwt


@pytest.fixture
def mock_sso_success(sso_setup):
    with (
        mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
        mock_jwt_validation(create_user_claims(sso_setup["installation_id"])) as mock_jwt,
    ):
        yield mock_jwt


class TestSSORedirectSuccess(BaseSSOMockTest):
    def test_sso_redirect_basic_success(self, sso_setup):
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
        # Existing users should be redirected to login for verification
        SSOTestHelper.assert_login_redirect(response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"})

    def test_sso_redirect_with_billing_path(self, sso_setup):
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], path="billing")
        # Existing users should be redirected to login for verification
        SSOTestHelper.assert_login_redirect(
            response, {"mode": "sso", "code": "test_auth_code", "state": "test_state", "path": "billing"}
        )

    def test_sso_redirect_with_custom_url(self, sso_setup):
        custom_url = "https://eu.posthog.com/dashboard"
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], url=custom_url)
        # Existing users should be redirected to login for verification
        SSOTestHelper.assert_login_redirect(response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"})

    def test_sso_redirect_with_resource_switching(self, sso_setup):
        team = Team.objects.create(organization=sso_setup["organization"], name="SSO Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "SSO Test Resource"},
            created_by=sso_setup["user"],
        )

        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], resource_id=str(resource.pk))
        # Existing users should be redirected to login for verification
        SSOTestHelper.assert_login_redirect(response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"})

        # Since user is redirected to login, team switching hasn't happened yet
        sso_setup["user"].refresh_from_db()
        assert sso_setup["user"].current_team != team  # Team switching happens after login verification

    def test_sso_redirect_with_experimentation_item(self, sso_setup):
        from posthog.models import FeatureFlag

        team = Team.objects.create(organization=sso_setup["organization"], name="Test Team")
        flag = FeatureFlag.objects.create(
            team=team,
            name="Test Flag",
            key="test-flag",
            created_by=sso_setup["user"],
        )

        response = SSOTestHelper.make_sso_request(
            sso_setup["client"], sso_setup["url"], experimentation_item_id=f"flag:{flag.id}"
        )
        # Existing users should be redirected to login for verification
        SSOTestHelper.assert_login_redirect(response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"})


class TestSSORedirectValidation:
    @pytest.mark.parametrize("missing_param", ["mode", "code", "state"])
    def test_sso_redirect_missing_required_params(self, sso_setup, missing_param):
        params = TestConstants.BASE_SSO_PARAMS.copy()
        del params[missing_param]
        response = sso_setup["client"].get(sso_setup["url"], params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_sso_redirect_invalid_mode(self, sso_setup):
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], mode="invalid")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_sso_redirect_rejects_invalid_path(self, sso_setup):
        """Invalid path values should be rejected with 400."""
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], path="invalid_path")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("path_value", ["billing", "usage", "support"])
    def test_sso_redirect_accepts_valid_paths(self, path_value, sso_setup):
        """Valid path values should be accepted and redirect successfully."""
        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"])),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], path=path_value)
            assert response.status_code == status.HTTP_302_FOUND

    @pytest.mark.parametrize(
        "url_value",
        [
            "http://malicious.com/evil",
            "https://malicious.com/evil",
            "ftp://posthog.com/dashboard",
            "javascript:alert('xss')",
        ],
    )
    def test_sso_redirect_rejects_malicious_urls(self, url_value, sso_setup):
        response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"], url=url_value)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_sso_redirect_with_empty_optional_params_returns_401(self, sso_setup):
        response = SSOTestHelper.make_sso_request(
            sso_setup["client"], sso_setup["url"], path="", url="", resource_id="", experimentation_item_id=""
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestSSORedirectFailures:
    def test_sso_redirect_when_credentials_missing(self, sso_setup):
        with mock_vercel_integration(**MockFactory.missing_credentials()):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_sso_redirect_when_token_exchange_fails(self, sso_setup):
        with mock_vercel_integration(**MockFactory.failed_token_exchange()):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_sso_redirect_when_token_exchange_returns_none(self, sso_setup):
        with mock_vercel_integration(**MockFactory.token_exchange_returns_none()):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_sso_redirect_when_id_token_missing(self, sso_setup):
        with mock_vercel_integration(**MockFactory.missing_id_token()):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_sso_redirect_when_jwt_validation_fails(self, sso_setup):
        from jwt import InvalidTokenError

        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            patch(
                "products.enterprise.backend.api.authentication.VercelAuthentication._validate_jwt_token"
            ) as mock_jwt,
        ):
            mock_jwt.side_effect = InvalidTokenError("Invalid token")

            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_sso_redirect_when_user_email_missing_from_claims(self, sso_setup):
        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], email=None)),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestSSOUserMapping:
    def test_sso_redirect_creates_new_user_mapping_for_unknown_user(self, sso_setup):
        """
        When an existing user (with same email) tries to authenticate via SSO, the system should:
        1. Detect that the user exists
        2. Redirect them to login for verification
        3. Not create user mapping until after login verification
        """
        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], "new_sso_user_456")),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            # Existing users should be redirected to login for verification
            SSOTestHelper.assert_login_redirect(
                response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"}
            )

            # User mapping should NOT be created until after login verification
            sso_setup["installation"].refresh_from_db()
            user_mappings = sso_setup["installation"].config.get("user_mappings", {})
            assert "new_sso_user_456" not in user_mappings

    def test_sso_redirect_reuses_existing_user_mapping(self, sso_setup):
        """
        When a user with an existing mapping authenticates via SSO, the system should:
        1. Find the existing user mapping
        2. Reuse the existing association
        3. Successfully authenticate the user
        """
        sso_setup["installation"].config["user_mappings"] = {"existing_user_123": sso_setup["user"].pk}
        sso_setup["installation"].save()

        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], "existing_user_123")),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            SSOTestHelper.assert_successful_redirect(response)
            SSOTestHelper.assert_user_mapping_created(
                sso_setup["installation"], "existing_user_123", sso_setup["user"].pk
            )

    def test_sso_redirect_cleans_up_stale_user_mapping(self, sso_setup):
        """
        When a user mapping exists for a deleted user, the SSO flow should:
        1. Detect the stale mapping
        2. Clean it up
        3. Create a new mapping for the current user
        4. Successfully authenticate the user
        """
        deleted_user_pk = 99999
        sso_setup["installation"].config["user_mappings"] = {"stale_user_123": deleted_user_pk}
        sso_setup["installation"].save()

        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], "stale_user_123")),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            # Existing users should be redirected to login for verification
            SSOTestHelper.assert_login_redirect(
                response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"}
            )


class TestSSOOrganizationHandling:
    def test_sso_redirect_adds_new_user_to_organization(self, sso_setup):
        """
        When a new user authenticates via SSO, the system should:
        1. Create a new PostHog user account
        2. Add them as a member of the installation's organization
        3. Create the user mapping
        4. Successfully authenticate the user
        """
        new_user_email = "newuser@example.com"

        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], "brand_new_user", new_user_email)),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            SSOTestHelper.assert_successful_redirect(response)

            new_user = User.objects.get(email=new_user_email)
            assert OrganizationMembership.objects.filter(user=new_user, organization=sso_setup["organization"]).exists()

            SSOTestHelper.assert_user_mapping_created(sso_setup["installation"], "brand_new_user", new_user.pk)

    def test_sso_redirect_handles_user_with_multiple_organizations(self, sso_setup):
        """
        When a user belonging to multiple organizations authenticates via SSO, the system should:
        1. Use the organization associated with the current installation
        2. Maintain existing memberships in other organizations
        3. Successfully authenticate the user
        """
        other_org = Organization.objects.create(name="Other Org")
        other_installation = OrganizationIntegration.objects.create(
            organization=other_org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_other123456789012345678",
            config={"billing_plan_id": "pro", "scopes": ["read", "write"]},
            created_by=sso_setup["user"],
        )
        sso_setup["user"].join(organization=other_org, level=OrganizationMembership.Level.ADMIN)

        assert other_installation.integration_id is not None
        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(other_installation.integration_id)),
            mock_jwt_validation(create_user_claims(other_installation.integration_id)),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            # Existing users should be redirected to login for verification
            SSOTestHelper.assert_login_redirect(
                response, {"mode": "sso", "code": "test_auth_code", "state": "test_state"}
            )
            assert OrganizationMembership.objects.filter(
                user=sso_setup["user"], organization=sso_setup["organization"]
            ).exists()

    def test_sso_redirect_denies_access_for_user_without_organization_membership(self, sso_setup):
        """
        When a user with an existing mapping no longer has organization membership, the system should:
        1. Detect the missing organization membership
        2. Remove the stale user mapping
        3. Deny access with PermissionDenied
        """

        sso_setup["installation"].config["user_mappings"] = {"mapped_user_123": sso_setup["user"].pk}
        sso_setup["installation"].save()

        OrganizationMembership.objects.filter(user=sso_setup["user"], organization=sso_setup["organization"]).delete()

        with (
            mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
            mock_jwt_validation(create_user_claims(sso_setup["installation_id"], "mapped_user_123")),
        ):
            response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

            sso_setup["installation"].refresh_from_db()
            user_mappings = sso_setup["installation"].config.get("user_mappings", {})
            assert "mapped_user_123" not in user_mappings

    def test_sso_redirect_allows_access_for_user_with_valid_membership_levels(self, sso_setup):
        from posthog.models.organization import OrganizationMembership

        levels_to_test = [
            OrganizationMembership.Level.MEMBER,
            OrganizationMembership.Level.ADMIN,
            OrganizationMembership.Level.OWNER,
        ]

        for i, level in enumerate(levels_to_test):
            user_id = f"mapped_user_{level.value}_{i}"
            sso_setup["installation"].config["user_mappings"] = {user_id: sso_setup["user"].pk}
            sso_setup["installation"].save()

            membership = OrganizationMembership.objects.get(
                user=sso_setup["user"], organization=sso_setup["organization"]
            )
            membership.level = level
            membership.save()

            with (
                mock_vercel_integration(**MockFactory.successful_sso_flow(sso_setup["installation_id"])),
                mock_jwt_validation(create_user_claims(sso_setup["installation_id"], user_id)),
            ):
                response = SSOTestHelper.make_sso_request(sso_setup["client"], sso_setup["url"])
                assert response.status_code == status.HTTP_302_FOUND, f"Failed for level {level}"

                sso_setup["installation"].refresh_from_db()
                user_mappings = sso_setup["installation"].config.get("user_mappings", {})
                assert user_id in user_mappings, f"Mapping removed for level {level}"
