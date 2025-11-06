import json
from typing import Any, Literal

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from posthog.models import Organization, Team
from posthog.models.organization_integration import OrganizationIntegration

from products.enterprise.backend.api.vercel.test.base import VercelTestBase
from products.enterprise.backend.api.vercel.types import VercelSystemClaims, VercelUser, VercelUserClaims
from products.enterprise.backend.api.vercel.vercel_permission import VercelPermission


class TestVercelPermission(VercelTestBase):
    def setUp(self):
        super().setUp()
        self.permission = VercelPermission()
        self.mock_view = MagicMock()
        self.mock_request = MagicMock()
        self.mock_request.user = VercelUser(claims=self._mock_user_claims())
        self.claims_patcher = patch("ee.api.vercel.vercel_permission.get_vercel_claims")
        self.mock_get_claims = self.claims_patcher.start()
        self.user_claim_patcher = patch("ee.api.vercel.vercel_permission.expect_vercel_user_claim")
        self.mock_expect_user_claim = self.user_claim_patcher.start()

    def tearDown(self):
        self.claims_patcher.stop()
        self.user_claim_patcher.stop()
        super().tearDown()

    def _mock_user_claims(self, user_role: Literal["ADMIN", "USER"] = "ADMIN", installation_id=None):
        return VercelUserClaims(
            iss="https://marketplace.vercel.com",
            sub="account:test:user:test",
            aud="test_audience",
            account_id="test_account",
            installation_id=installation_id or self.installation_id,
            user_id="test_user",
            user_role=user_role,
            type=None,
            user_avatar_url=None,
            user_email=None,
            user_name=None,
        )

    def _mock_system_claims(self, installation_id=None):
        return VercelSystemClaims(
            iss="https://marketplace.vercel.com",
            sub="account:test",
            aud="test_audience",
            account_id="test_account",
            installation_id=installation_id or self.installation_id,
            type=None,
        )

    def _setup_request(
        self,
        auth_type="user",
        action="update",
        supported_types=None,
        user_role: Literal["ADMIN", "USER"] = "ADMIN",
        installation_id=None,
        headers=None,
    ):
        if headers is not None:
            self.mock_request.headers = headers
        else:
            self.mock_request.headers = {"X-Vercel-Auth": auth_type}

        self.mock_view.action = action
        if supported_types:
            self.mock_view.vercel_supported_auth_types = {action: supported_types}

        if headers is not None and not headers:
            return  # Don't set up claims for empty header dicts

        if auth_type.lower() == "user":
            user_claims = self._mock_user_claims(user_role, installation_id)
            self.mock_get_claims.return_value = user_claims
            self.mock_expect_user_claim.return_value = user_claims
        else:
            system_claims = self._mock_system_claims(installation_id)
            self.mock_get_claims.return_value = system_claims

    def _assert_permission_denied(self, func, expected_msg):
        with pytest.raises(PermissionDenied) as exc_info:
            func()
        assert expected_msg in str(exc_info.value.detail)

    def _assert_auth_failed(self, func, expected_msg):
        with pytest.raises(AuthenticationFailed) as exc_info:
            func()
        assert expected_msg in str(exc_info.value.detail)

    def test_has_permission_validates_auth_type(self):
        self._setup_request(action="update", supported_types=["user"], user_role="ADMIN")
        assert self.permission.has_permission(self.mock_request, self.mock_view) is True

    def test_has_permission_missing_auth_header(self):
        self._setup_request(headers={})
        self._assert_auth_failed(
            lambda: self.permission.has_permission(self.mock_request, self.mock_view), "Missing X-Vercel-Auth header"
        )

    def test_has_permission_invalid_auth_type(self):
        self._setup_request(auth_type="system", supported_types=["user"])
        self._assert_permission_denied(
            lambda: self.permission.has_permission(self.mock_request, self.mock_view),
            "Auth type 'system' not allowed for this endpoint",
        )

    @parameterized.expand(
        [
            (
                {"installation_id": VercelTestBase.TEST_INSTALLATION_ID},
                {"installation_id": VercelTestBase.TEST_INSTALLATION_ID},
                True,
                None,
            ),
            (
                {"installation_id": VercelTestBase.TEST_INSTALLATION_ID},
                {"installation_id": VercelTestBase.OTHER_INSTALLATION_ID},
                False,
                "Installation ID mismatch",
            ),
            ({}, {"installation_id": VercelTestBase.TEST_INSTALLATION_ID}, False, "Missing installation_id"),
            (
                {"parent_lookup_installation_id": VercelTestBase.TEST_INSTALLATION_ID},
                {"installation_id": VercelTestBase.TEST_INSTALLATION_ID},
                True,
                None,
            ),
        ]
    )
    def test_installation_id_validation(self, view_kwargs, claims, should_pass, error_msg):
        self.mock_view.kwargs = view_kwargs
        auth_type = "user" if "user_role" in claims else "system"
        self._setup_request(auth_type=auth_type, installation_id=claims.get("installation_id"))

        if should_pass:
            assert self.permission.has_object_permission(self.mock_request, self.mock_view, None) is True
        else:
            with pytest.raises(PermissionDenied) as exc_info:
                self.permission.has_object_permission(self.mock_request, self.mock_view, None)
            assert str(exc_info.value.detail) == error_msg

    def test_has_object_permission_no_jwt_auth(self):
        self.mock_view.kwargs = {"installation_id": VercelTestBase.TEST_INSTALLATION_ID}
        self.mock_get_claims.reset_mock()
        self.mock_get_claims.side_effect = AuthenticationFailed("Not authenticated with Vercel")
        self._assert_auth_failed(
            lambda: self.permission.has_object_permission(self.mock_request, self.mock_view, None),
            "Not authenticated with Vercel",
        )

    def test_get_supported_auth_types_default(self):
        self.mock_view.action = "list"
        if hasattr(self.mock_view, "vercel_supported_auth_types"):
            delattr(self.mock_view, "vercel_supported_auth_types")
        auth_types = self.permission._get_supported_auth_types(self.mock_view)
        assert auth_types == ["user", "system"]

    def test_get_supported_auth_types_custom(self):
        self.mock_view.action = "destroy"
        self.mock_view.vercel_supported_auth_types = {"destroy": ["user", "system"], "update": ["user"]}
        auth_types = self.permission._get_supported_auth_types(self.mock_view)
        assert auth_types == ["user", "system"]

    def test_auth_type_case_insensitive(self):
        self._setup_request(auth_type="USER", supported_types=["user"], user_role="ADMIN")
        assert self.permission.has_permission(self.mock_request, self.mock_view) is True

    @parameterized.expand(
        [
            ("update", "ADMIN", True, None),
            ("update", "USER", False, "requires ADMIN role"),
            ("destroy", "ADMIN", True, None),
            ("destroy", "USER", False, "requires ADMIN role"),
            ("retrieve", "USER", True, None),
            ("retrieve", "ADMIN", True, None),
        ]
    )
    def test_role_permissions(self, action, user_role, should_pass, error_msg):
        self._setup_request(action=action, supported_types=["user"], user_role=user_role)
        if should_pass:
            assert self.permission.has_permission(self.mock_request, self.mock_view) is True
        else:
            with pytest.raises(PermissionDenied) as exc_info:
                self.permission.has_permission(self.mock_request, self.mock_view)
            assert error_msg in str(exc_info.value.detail)

    def test_system_auth_bypasses_role_check(self):
        self._setup_request(auth_type="system", supported_types=["system"])
        assert self.permission.has_permission(self.mock_request, self.mock_view) is True

    def test_missing_role_denied_for_admin_action(self):
        self._setup_request(action="update", supported_types=["user"], user_role="USER")
        self._assert_permission_denied(
            lambda: self.permission.has_permission(self.mock_request, self.mock_view), "requires ADMIN role"
        )


class TestVercelPermissionIntegration(VercelTestBase):
    client_id_patcher: Any
    jwks_patcher: Any
    mock_get_jwks: Any

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_id_patcher = patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
        cls.jwks_patcher = patch("ee.api.authentication.get_vercel_jwks")
        cls.client_id_patcher.start()
        cls.mock_get_jwks = cls.jwks_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.client_id_patcher.stop()
        cls.jwks_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.mock_get_jwks.return_value = self.mock_jwks
        self.url = f"/api/vercel/v1/installations/{self.installation_id}/"

    def _make_request(
        self, method, jwt_installation_id=None, user_role="ADMIN", auth_type="user", data=None, url_installation_id=None
    ):
        jwt_installation_id = jwt_installation_id or self.installation_id
        url_installation_id = url_installation_id or self.installation_id
        payload = (
            self._create_user_auth_payload(installation_id=jwt_installation_id, user_role=user_role)
            if auth_type == "user"
            else self._create_system_auth_payload(installation_id=jwt_installation_id)
        )
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self._create_jwt_token(payload)}",
            "HTTP_X_VERCEL_AUTH": auth_type,
        }
        url = f"/api/vercel/v1/installations/{url_installation_id}/"
        kwargs = dict(**headers)
        if data:
            kwargs.update(content_type="application/json", data=json.dumps(data))
        return getattr(self.client, method)(url, **kwargs)

    @parameterized.expand(
        [
            (
                "patch",
                VercelTestBase.OTHER_INSTALLATION_ID,
                None,
                "user",
                {"billingPlanId": "pro200"},
                status.HTTP_204_NO_CONTENT,
            ),
            ("delete", VercelTestBase.OTHER_INSTALLATION_ID, None, "user", None, status.HTTP_200_OK),
            ("patch", None, None, "system", {"billingPlanId": "pro200"}, status.HTTP_403_FORBIDDEN),
            ("get", None, None, "user", None, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_auth_validation(self, method, jwt_id, url_id, auth_type, data, expected_status):
        response = self._make_request(
            method, jwt_installation_id=jwt_id, url_installation_id=url_id, auth_type=auth_type, data=data
        )
        assert response.status_code == expected_status

    @parameterized.expand(
        [
            ("patch", "ADMIN", {"billingPlanId": "pro200"}, status.HTTP_204_NO_CONTENT),
            ("patch", "USER", {"billingPlanId": "pro200"}, status.HTTP_403_FORBIDDEN),
            ("delete", "USER", None, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_role_based_access(self, method, user_role, data, expected_status):
        response = self._make_request(method, user_role=user_role, data=data)
        assert response.status_code == expected_status

    def test_cross_organization_access_denied(self):
        other_org = Organization.objects.create(name="Other Org")
        Team.objects.create(organization=other_org, name="Other Team")
        other_installation_id = VercelTestBase.OTHER_INSTALLATION_ID
        OrganizationIntegration.objects.create(
            organization=other_org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=other_installation_id,
            config={"billing_plan_id": "free"},
            created_by=self.user,
        )
        response = self._make_request(
            "patch",
            jwt_installation_id=other_installation_id,
            url_installation_id=other_installation_id,
            data={"billingPlanId": "pro200"},
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
