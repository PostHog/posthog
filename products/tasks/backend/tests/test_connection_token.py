import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.tasks.backend.services.connection_token import (
    SANDBOX_CONNECTION_AUDIENCE,
    SANDBOX_JWT_STATE_KID_KEY,
    _compute_kid,
    _derive_public_key_pem,
    create_sandbox_connection_token,
    create_sandbox_event_ingest_token,
    get_primary_sandbox_jwt_kid,
    get_sandbox_jwt_public_key,
    reset_sandbox_jwt_key_cache,
    validate_sandbox_event_ingest_token,
)


def _generate_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


KEY_A = _generate_private_key_pem()
KEY_B = _generate_private_key_pem()
KID_A = _compute_kid(_derive_public_key_pem(KEY_A))


def _fake_run(state: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        team_id=1,
        mode="background",
        state=state if state is not None else {},
    )


class TestSandboxJwtRotation(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_sandbox_jwt_key_cache()

    def tearDown(self) -> None:
        reset_sandbox_jwt_key_cache()
        super().tearDown()

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None)
    def test_primary_only_signs_and_verifies_with_primary(self) -> None:
        reset_sandbox_jwt_key_cache()
        self.assertEqual(get_primary_sandbox_jwt_kid(), KID_A)

        token = create_sandbox_connection_token(_fake_run(), user_id=1, distinct_id="d")
        decoded = jwt.decode(
            token, _derive_public_key_pem(KEY_A), algorithms=["RS256"], audience=SANDBOX_CONNECTION_AUDIENCE
        )
        self.assertEqual(jwt.get_unverified_header(token)["kid"], KID_A)
        self.assertEqual(decoded["aud"], SANDBOX_CONNECTION_AUDIENCE)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A)
    def test_connection_token_signed_with_run_stored_kid(self) -> None:
        reset_sandbox_jwt_key_cache()
        # Primary is now KEY_B, but this run's sandbox was provisioned under KEY_A.
        run = _fake_run({SANDBOX_JWT_STATE_KID_KEY: KID_A})
        token = create_sandbox_connection_token(run, user_id=1, distinct_id="d")

        self.assertEqual(jwt.get_unverified_header(token)["kid"], KID_A)
        # Verifies against the old (KEY_A) public key the sandbox still holds...
        jwt.decode(token, _derive_public_key_pem(KEY_A), algorithms=["RS256"], audience=SANDBOX_CONNECTION_AUDIENCE)
        # ...and is rejected by the new primary key.
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, _derive_public_key_pem(KEY_B), algorithms=["RS256"], audience=SANDBOX_CONNECTION_AUDIENCE)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None)
    def test_fallback_to_primary_when_no_kid_stored(self) -> None:
        reset_sandbox_jwt_key_cache()
        token = create_sandbox_connection_token(_fake_run({}), user_id=1, distinct_id="d")
        self.assertEqual(jwt.get_unverified_header(token)["kid"], KID_A)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A)
    def test_ingest_token_always_uses_primary_ignoring_run_kid(self) -> None:
        reset_sandbox_jwt_key_cache()
        # The ingest path is single-key: it signs/validates with the primary key only and
        # ignores the run's stored kid (unlike the connection token).
        token = create_sandbox_event_ingest_token(_fake_run({SANDBOX_JWT_STATE_KID_KEY: KID_A}))
        self.assertNotIn("kid", jwt.get_unverified_header(token))
        payload = validate_sandbox_event_ingest_token(token)
        self.assertEqual(payload.team_id, 1)

    def test_ingest_token_rejected_after_primary_rotation(self) -> None:
        # Ingest is intentionally NOT rotation-safe: a token signed under the old primary
        # stops validating once the primary is rotated, even if the old key is kept as secondary.
        with override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None):
            reset_sandbox_jwt_key_cache()
            token = create_sandbox_event_ingest_token(_fake_run())

        with override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A):
            reset_sandbox_jwt_key_cache()
            with self.assertRaises(jwt.InvalidTokenError):
                validate_sandbox_event_ingest_token(token)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None)
    def test_connection_token_rejected_as_ingest_token(self) -> None:
        reset_sandbox_jwt_key_cache()
        # A connection-audience token must not pass ingest validation (wrong audience).
        token = create_sandbox_connection_token(_fake_run(), user_id=1, distinct_id="d")
        with self.assertRaises(jwt.InvalidTokenError):
            validate_sandbox_event_ingest_token(token)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A)
    def test_duplicate_primary_and_secondary_collapse_to_one_key(self) -> None:
        reset_sandbox_jwt_key_cache()
        token = create_sandbox_event_ingest_token(_fake_run({SANDBOX_JWT_STATE_KID_KEY: KID_A}))
        payload = validate_sandbox_event_ingest_token(token)
        self.assertEqual(payload.team_id, 1)
        self.assertEqual(get_primary_sandbox_jwt_kid(), KID_A)
        self.assertEqual(get_sandbox_jwt_public_key(), _derive_public_key_pem(KEY_A))
