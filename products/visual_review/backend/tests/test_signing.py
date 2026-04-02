import re

from parameterized import parameterized

from products.visual_review.backend.signing import (
    SIGNED_HASH_RE,
    generate_signing_key,
    parse_signed_hash,
    sign_snapshot_hash,
    verify_signed_hash,
)

REPO_ID = "550e8400-e29b-41d4-a716-446655440000"
IDENTIFIER = "button--primary--light"
CONTENT_HASH = "a" * 64  # valid 64-char hex


class TestGenerateSigningKey:
    def test_kid_format(self):
        kid, _ = generate_signing_key()
        assert re.fullmatch(r"k[0-9a-f]{8}", kid)

    def test_secret_is_64_hex_chars(self):
        _, secret = generate_signing_key()
        assert re.fullmatch(r"[0-9a-f]{64}", secret)

    def test_keys_are_unique(self):
        pairs = [generate_signing_key() for _ in range(10)]
        kids = [k for k, _ in pairs]
        secrets = [s for _, s in pairs]
        assert len(set(kids)) == 10
        assert len(set(secrets)) == 10


class TestSignSnapshotHash:
    def test_format_matches_grammar(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert SIGNED_HASH_RE.match(signed), f"Signed hash does not match grammar: {signed}"

    def test_embeds_content_hash(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        parts = signed.split(".")
        assert parts[2] == CONTENT_HASH

    def test_embeds_kid(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        parts = signed.split(".")
        assert parts[1] == kid

    def test_deterministic(self):
        kid, secret = generate_signing_key()
        a = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        b = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert a == b

    def test_different_identifiers_produce_different_tags(self):
        kid, secret = generate_signing_key()
        a = sign_snapshot_hash(REPO_ID, "id-a", CONTENT_HASH, secret, kid)
        b = sign_snapshot_hash(REPO_ID, "id-b", CONTENT_HASH, secret, kid)
        assert a.split(".")[3] != b.split(".")[3]


class TestParseSignedHash:
    def test_valid(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        parsed = parse_signed_hash(signed)
        assert parsed is not None
        assert parsed.kid == kid
        assert parsed.content_hash == CONTENT_HASH
        assert len(parsed.tag_b64url) == 43

    @parameterized.expand(
        [
            ("empty", ""),
            ("no_dots", "v1k1aabbcc"),
            ("wrong_version", "v2.k1." + "a" * 64 + ".x" * 43),
            ("short_hash", "v1.k1." + "a" * 63 + "." + "A" * 43),
            ("non_hex_hash", "v1.k1." + "g" * 64 + "." + "A" * 43),
            ("short_tag", "v1.k1." + "a" * 64 + "." + "A" * 42),
            ("kid_too_long", "v1." + "k" * 33 + "." + "a" * 64 + "." + "A" * 43),
        ]
    )
    def test_rejects_invalid(self, _name, value):
        assert parse_signed_hash(value) is None


class TestVerifySignedHash:
    def test_roundtrip(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        result = verify_signed_hash(REPO_ID, IDENTIFIER, signed, {kid: secret})
        assert result == CONTENT_HASH

    def test_wrong_secret_rejected(self):
        kid, secret = generate_signing_key()
        _, other_secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert verify_signed_hash(REPO_ID, IDENTIFIER, signed, {kid: other_secret}) is None

    def test_unknown_kid_rejected(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert verify_signed_hash(REPO_ID, IDENTIFIER, signed, {"other": secret}) is None

    def test_tampered_hash_rejected(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        tampered = signed.replace(CONTENT_HASH, "b" * 64)
        assert verify_signed_hash(REPO_ID, IDENTIFIER, tampered, {kid: secret}) is None

    def test_wrong_identifier_rejected(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert verify_signed_hash(REPO_ID, "wrong-id", signed, {kid: secret}) is None

    def test_wrong_repo_rejected(self):
        kid, secret = generate_signing_key()
        signed = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret, kid)
        assert verify_signed_hash("other-repo-id", IDENTIFIER, signed, {kid: secret}) is None

    def test_key_rotation(self):
        kid1, secret1 = generate_signing_key()
        kid2, secret2 = generate_signing_key()
        keys = {kid1: secret1, kid2: secret2}

        signed_old = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret1, kid1)
        signed_new = sign_snapshot_hash(REPO_ID, IDENTIFIER, CONTENT_HASH, secret2, kid2)

        assert verify_signed_hash(REPO_ID, IDENTIFIER, signed_old, keys) == CONTENT_HASH
        assert verify_signed_hash(REPO_ID, IDENTIFIER, signed_new, keys) == CONTENT_HASH

    def test_garbage_input(self):
        assert verify_signed_hash(REPO_ID, IDENTIFIER, "not-a-signed-hash", {}) is None
