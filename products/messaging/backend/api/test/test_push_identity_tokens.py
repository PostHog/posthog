import hmac
import json
import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized

from products.messaging.backend.api.push_identity_tokens import (
    PUSH_IDENTITY_TOKEN_AUDIENCE,
    sign_push_identity_token_es256,
    verify_push_identity_token,
)


# A fresh EC P-256 keypair as (private PEM, public PEM): the customer's signing key and the public
# half they register with PostHog.
def _es256_keypair() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


# Hand-roll an HS256 JWT: PyJWT refuses to sign HMAC with a PEM public key (it blocks alg confusion at
# the encode step), so an attacker crafting this token wouldn't use PyJWT either.
def _forge_hs256(secret: str, claims: dict) -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(claims).encode())}"
    signature = b64(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


DISTINCT_ID = "user-1"
APP_ID = "my-firebase-project"


class TestPushIdentityTokens(SimpleTestCase):
    def test_verifies_a_token_signed_by_the_registered_public_key(self) -> None:
        private_pem, public_pem = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is True

    @parameterized.expand(
        [
            ("wrong_distinct_id", "someone-else", APP_ID),
            ("wrong_app_id", DISTINCT_ID, "other-app"),
        ]
    )
    def test_rejects_a_token_whose_claims_do_not_match_the_registration(self, _name, sub, app_id):
        # The rebind guard: a token minted for one (distinct_id, app_id) cannot authorize a different one.
        private_pem, public_pem = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, sub, app_id)
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False

    def test_rejects_a_token_when_a_different_public_key_is_registered(self) -> None:
        signer_private, _ = _es256_keypair()
        _, registered_public = _es256_keypair()
        token = sign_push_identity_token_es256(signer_private, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[registered_public]) is False

    def test_rejects_an_expired_token(self):
        private_pem, public_pem = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID, ttl=timedelta(seconds=-1))
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False

    def test_rejects_a_token_with_no_exp_claim(self):
        # An external signer could omit exp; without requiring it a token would never expire, so the
        # verifier must reject it even though the signature is valid.
        private_pem, public_pem = _es256_keypair()
        token = jwt.encode(
            {"sub": DISTINCT_ID, "app_id": APP_ID, "aud": PUSH_IDENTITY_TOKEN_AUDIENCE},
            private_pem,
            algorithm="ES256",
        )
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False

    def test_rejects_a_malformed_token(self):
        _, public_pem = _es256_keypair()
        assert verify_push_identity_token("not-a-jwt", DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False

    def test_rejects_every_token_when_no_public_key_is_registered(self) -> None:
        private_pem, _ = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID) is False

    def test_returns_false_without_crashing_for_a_mismatched_curve_public_key(self):
        # A registered key on the wrong curve makes jwt.decode raise InvalidKeyError, which is not an
        # InvalidTokenError. verify must treat it as unverified rather than let it crash the endpoint.
        private_pem, _ = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID)
        p384_public = (
            ec.generate_private_key(ec.SECP384R1())
            .public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        assert verify_push_identity_token(token, DISTINCT_ID, APP_ID, public_keys=[p384_public]) is False

    def test_rejects_a_token_signed_with_a_project_secret(self):
        # The shared-secret scheme this endpoint used to accept. A project that still signs that way
        # gets a 401 rather than a silent downgrade to a weaker check.
        _, public_pem = _es256_keypair()
        forged = _forge_hs256(
            secrets.token_hex(32),
            {
                "sub": DISTINCT_ID,
                "app_id": APP_ID,
                "aud": PUSH_IDENTITY_TOKEN_AUDIENCE,
                "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            },
        )
        assert verify_push_identity_token(forged, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False

    def test_rejects_hs256_token_forged_with_the_public_key_as_the_hmac_secret(self):
        # JWT algorithm confusion: the public key is public, so an attacker can sign an HS256 token
        # using it as the HMAC secret. Verifying a public key only under ES256 rejects this; allowing
        # both algorithms per key would let anyone forge an identity for any distinct_id.
        _, public_pem = _es256_keypair()
        forged = _forge_hs256(
            public_pem,
            {
                "sub": DISTINCT_ID,
                "app_id": APP_ID,
                "aud": PUSH_IDENTITY_TOKEN_AUDIENCE,
                "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            },
        )
        assert verify_push_identity_token(forged, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False
