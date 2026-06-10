from posthog.test.base import APIBaseTest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rest_framework import status

from products.error_tracking.backend.api.signing_keys import derive_key_id
from products.error_tracking.backend.models import ErrorTrackingSigningKey

# Fixed keypair matching the SDK parity vector (seed = bytes(range(32))).
SEED = bytes(range(32))
PARITY_KEY_ID = "Vkdap1RjR0wChd9d"


def _public_key_pem(seed=SEED) -> str:
    pub = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    return pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class TestSigningKeyAPI(APIBaseTest):
    def _url(self, key_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/signing_keys/"
        return f"{base}{key_id}/" if key_id else base

    def test_create_derives_key_id_matching_the_sdk(self) -> None:
        response = self.client.post(self._url(), data={"public_key": _public_key_pem(), "label": "prod backend"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        # The server-derived key_id must equal what the SDK stamps on signed events.
        self.assertEqual(body["key_id"], PARITY_KEY_ID)
        self.assertEqual(body["label"], "prod backend")
        self.assertFalse(body["revoked"])

        row = ErrorTrackingSigningKey.objects.get(id=body["id"])
        self.assertEqual(row.team_id, self.team.id)
        self.assertEqual(row.created_by, self.user)

    def test_key_id_derivation_matches_helper(self) -> None:
        raw = (
            Ed25519PrivateKey.from_private_bytes(SEED)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
        self.assertEqual(derive_key_id(raw), PARITY_KEY_ID)

    def test_rejects_non_ed25519_key(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_pem = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        response = self.client.post(self._url(), data={"public_key": rsa_pem})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Ed25519", str(response.json()))

    def test_rejects_garbage_key(self) -> None:
        response = self.client.post(self._url(), data={"public_key": "not a pem key"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_is_team_scoped(self) -> None:
        ErrorTrackingSigningKey.objects.create(
            team=self.team, key_id="aaaa", public_key=_public_key_pem(), label="mine"
        )
        other = self.create_team_with_organization(self.organization)
        ErrorTrackingSigningKey.objects.create(team=other, key_id="bbbb", public_key=_public_key_pem(), label="theirs")
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        labels = {k["label"] for k in response.json()["results"]}
        self.assertEqual(labels, {"mine"})

    def test_revoke_via_patch(self) -> None:
        created = self.client.post(self._url(), data={"public_key": _public_key_pem()}).json()
        response = self.client.patch(self._url(created["id"]), data={"revoked": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ErrorTrackingSigningKey.objects.get(id=created["id"]).revoked)

    def test_public_key_is_immutable_on_update(self) -> None:
        created = self.client.post(self._url(), data={"public_key": _public_key_pem()}).json()
        original = created["public_key"]
        original_key_id = created["key_id"]
        # A *valid but different* key is silently ignored on update (read-only), not applied.
        different = _public_key_pem(seed=bytes(reversed(range(32))))
        self.assertNotEqual(different, original)
        response = self.client.patch(self._url(created["id"]), data={"public_key": different})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = ErrorTrackingSigningKey.objects.get(id=created["id"])
        self.assertEqual(row.public_key, original)
        self.assertEqual(row.key_id, original_key_id)
