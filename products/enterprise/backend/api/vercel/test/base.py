import base64

from posthog.test.base import APIBaseTest

from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.models.organization_integration import OrganizationIntegration

from products.enterprise.backend.api.authentication import VercelAuthentication


class VercelTestBase(APIBaseTest):
    # Test installation ID constants
    TEST_INSTALLATION_ID = "icfg_9bceb8ccT32d3U417ezb5c8p"
    OTHER_INSTALLATION_ID = "icfg_987654321abcdef123456789"

    def setUp(self):
        super().setUp()
        self.installation_id = self.TEST_INSTALLATION_ID
        self.account_id = "acc987654321"
        self.user_id = "111222333abc"

        self.installation = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=self.installation_id,
            config={
                "billing_plan_id": "free",
                "scopes": ["read", "write"],
                "credentials": {"access_token": "test_token", "token_type": "Bearer"},
            },
            created_by=self.user,
        )

        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()

        public_numbers = self.public_key.public_numbers()
        n = self._int_to_base64url(public_numbers.n)
        e = self._int_to_base64url(public_numbers.e)

        self.test_kid = "test_key_id"
        self.mock_jwks = {"keys": [{"kid": self.test_kid, "kty": "RSA", "use": "sig", "alg": "RS256", "n": n, "e": e}]}

    def _int_to_base64url(self, value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_length, byteorder="big")
        return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

    def _create_jwt_token(self, payload: dict, headers: dict | None = None) -> str:
        if headers is None:
            headers = {"kid": self.test_kid}

        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_key_str = private_key_pem.decode("utf-8")

        return jwt.encode(payload, private_key_str, algorithm="RS256", headers=headers)

    def _create_user_auth_payload(
        self,
        installation_id: str | None = None,
        account_id: str | None = None,
        user_id: str | None = None,
        user_role: str = "ADMIN",
    ) -> dict:
        return {
            "iss": VercelAuthentication.VERCEL_ISSUER,
            "sub": f"account:{account_id or self.account_id}:user:{user_id or self.user_id}",
            "aud": "test_audience",
            "account_id": account_id or self.account_id,
            "installation_id": installation_id or self.installation_id,
            "user_id": user_id or self.user_id,
            "user_role": user_role,
            "exp": timezone.now().timestamp() + 3600,
        }

    def _create_system_auth_payload(self, installation_id: str | None = None, account_id: str | None = None) -> dict:
        account = account_id or self.account_id
        return {
            "iss": VercelAuthentication.VERCEL_ISSUER,
            "sub": f"account:{account[3:] if account.startswith('acc') else account}",
            "aud": "test_audience",
            "account_id": account,
            "installation_id": installation_id or self.installation_id,
            "exp": timezone.now().timestamp() + 3600,
        }

    def _get_auth_headers(self, auth_type: str = "user") -> dict:
        if auth_type == "user":
            token = self._create_jwt_token(self._create_user_auth_payload())
        elif auth_type == "system":
            token = self._create_jwt_token(self._create_system_auth_payload())
        else:
            raise ValueError(f"Unsupported auth type: {auth_type}")

        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}
