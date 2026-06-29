import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from django.test import SimpleTestCase, override_settings

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_CONNECTION_AUDIENCE,
    SANDBOX_JWT_STATE_KID_KEY,
    _compute_kid,
    _derive_public_key_pem,
    create_sandbox_connection_token,
    create_sandbox_event_ingest_token,
    create_stream_read_token,
    get_primary_sandbox_jwt_kid,
    get_sandbox_jwt_public_key,
    reset_sandbox_jwt_key_cache,
    validate_sandbox_event_ingest_token,
    validate_stream_read_token,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.tests.test_api import TEST_RSA_PRIVATE_KEY


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


def _fake_run(state: dict | None = None) -> TaskRun:
    # Only the attributes the token helpers read are needed, so a lightweight stand-in
    # avoids the DB; cast keeps the call sites type-correct.
    return cast(
        TaskRun,
        SimpleNamespace(
            id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            team_id=1,
            mode="background",
            state=state if state is not None else {},
        ),
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

    @override_settings(
        SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A, SANDBOX_JWT_PUBLIC_KEY=None
    )
    def test_ingest_token_signed_with_run_stored_kid(self) -> None:
        reset_sandbox_jwt_key_cache()
        # Like the connection token, the ingest token now carries a kid and is signed with the key
        # the run was provisioned under, so the agent-proxy legs survive a primary-key rotation.
        token = create_sandbox_event_ingest_token(_fake_run({SANDBOX_JWT_STATE_KID_KEY: KID_A}))
        self.assertEqual(jwt.get_unverified_header(token)["kid"], KID_A)
        payload = validate_sandbox_event_ingest_token(token)
        self.assertEqual(payload.team_id, 1)

    def test_ingest_token_validates_after_primary_rotation(self) -> None:
        # Ingest is rotation-safe: a token signed under the old primary keeps validating after the
        # primary rotates, as long as the old key is retained as the secondary.
        with override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None):
            reset_sandbox_jwt_key_cache()
            token = create_sandbox_event_ingest_token(_fake_run())

        with override_settings(
            SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A, SANDBOX_JWT_PUBLIC_KEY=None
        ):
            reset_sandbox_jwt_key_cache()
            payload = validate_sandbox_event_ingest_token(token)
            self.assertEqual(payload.team_id, 1)

        # Once the old key is dropped entirely the token no longer validates.
        with override_settings(
            SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None, SANDBOX_JWT_PUBLIC_KEY=None
        ):
            reset_sandbox_jwt_key_cache()
            with self.assertRaises(jwt.InvalidTokenError):
                validate_sandbox_event_ingest_token(token)

    def test_stream_read_token_validates_after_primary_rotation(self) -> None:
        # The stream-read leg must survive rotation the same way ingest does: a token signed under
        # the old primary keeps validating while the old key is retained as the secondary.
        with override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None):
            reset_sandbox_jwt_key_cache()
            token = create_stream_read_token(_fake_run())

        with override_settings(
            SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A, SANDBOX_JWT_PUBLIC_KEY=None
        ):
            reset_sandbox_jwt_key_cache()
            payload = validate_stream_read_token(token)
            self.assertEqual(payload.team_id, 1)

        with override_settings(
            SANDBOX_JWT_PRIVATE_KEY=KEY_B, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None, SANDBOX_JWT_PUBLIC_KEY=None
        ):
            reset_sandbox_jwt_key_cache()
            with self.assertRaises(jwt.InvalidTokenError):
                validate_stream_read_token(token)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None)
    def test_connection_token_rejected_as_ingest_token(self) -> None:
        reset_sandbox_jwt_key_cache()
        # A connection-audience token must not pass ingest validation (wrong audience).
        token = create_sandbox_connection_token(_fake_run(), user_id=1, distinct_id="d")
        with self.assertRaises(jwt.InvalidTokenError):
            validate_sandbox_event_ingest_token(token)

    @override_settings(
        SANDBOX_JWT_PRIVATE_KEY=KEY_A, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=KEY_A, SANDBOX_JWT_PUBLIC_KEY=None
    )
    def test_duplicate_primary_and_secondary_collapse_to_one_key(self) -> None:
        reset_sandbox_jwt_key_cache()
        token = create_sandbox_event_ingest_token(_fake_run({SANDBOX_JWT_STATE_KID_KEY: KID_A}))
        payload = validate_sandbox_event_ingest_token(token)
        self.assertEqual(payload.team_id, 1)
        self.assertEqual(get_primary_sandbox_jwt_kid(), KID_A)
        self.assertEqual(get_sandbox_jwt_public_key(), _derive_public_key_pem(KEY_A))


_RUN_ID = "11111111-1111-1111-1111-111111111111"
_TASK_ID = "22222222-2222-2222-2222-222222222222"


def _fake_task_run() -> TaskRun:
    return cast(TaskRun, SimpleNamespace(id=_RUN_ID, task_id=_TASK_ID, team_id=7, state={}))


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
def test_stream_read_token_roundtrip():
    reset_sandbox_jwt_key_cache()
    token = create_stream_read_token(_fake_task_run())

    claims = validate_stream_read_token(token)

    assert claims.run_id == _RUN_ID
    assert claims.task_id == _TASK_ID
    assert claims.team_id == 7


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
def test_stream_read_token_rejects_expired():
    reset_sandbox_jwt_key_cache()
    token = create_stream_read_token(_fake_task_run(), ttl=timedelta(seconds=-1))

    with pytest.raises(jwt.ExpiredSignatureError):
        validate_stream_read_token(token)


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
def test_stream_read_token_is_not_accepted_for_event_ingest():
    reset_sandbox_jwt_key_cache()
    token = create_stream_read_token(_fake_task_run())

    with pytest.raises(jwt.InvalidAudienceError):
        validate_sandbox_event_ingest_token(token)


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
def test_event_ingest_token_is_not_accepted_for_stream_read():
    reset_sandbox_jwt_key_cache()
    token = create_sandbox_event_ingest_token(_fake_task_run())

    with pytest.raises(jwt.InvalidAudienceError):
        validate_stream_read_token(token)


def _public_key_for(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None, backend=default_backend())
    return (
        private_key.public_key()
        .public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def test_stream_read_token_validates_with_public_key_only():
    # Django mints with the private key; a verify-only service (agent-proxy) validates with ONLY
    # the public key configured and no private key present.
    with override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None):
        reset_sandbox_jwt_key_cache()
        token = create_stream_read_token(_fake_task_run())

    with override_settings(SANDBOX_JWT_PRIVATE_KEY=None, SANDBOX_JWT_PUBLIC_KEY=_public_key_for(TEST_RSA_PRIVATE_KEY)):
        reset_sandbox_jwt_key_cache()
        claims = validate_stream_read_token(token)

    assert claims.run_id == _RUN_ID
    assert claims.team_id == 7
    reset_sandbox_jwt_key_cache()
