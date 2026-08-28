from posthog.test.base import APIBaseTest

from rest_framework import status

from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagVersionHistoryAPI(APIBaseTest):
    def _create_remote_config_flag(self, *, encrypted: bool = False) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="ios-minimum-version",
            name="Minimum app version required",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '"1.0.0"'},
            },
            is_remote_configuration=True,
            has_encrypted_payloads=encrypted,
            version=1,
        )

    def test_plaintext_remote_config_flag_returns_historical_payload(self):
        flag = self._create_remote_config_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"2.0.0"'},
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["is_historical"])
        # The point of reconstruction: the payload served at the time, not the current one.
        self.assertEqual(payload["filters"]["payloads"], {"true": '"1.0.0"'})

    def test_encrypted_payload_flag_is_refused(self):
        flag = self._create_remote_config_flag(encrypted=True)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("filters", response.json())

    def test_version_encrypted_before_downgrade_is_refused(self):
        ciphertext = "gAAAAA-ciphertext-sentinel"
        flag = self._create_remote_config_flag(encrypted=True)
        flag.filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": ciphertext},
        }
        flag.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"has_encrypted_payloads": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertFalse(flag.has_encrypted_payloads)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        # The live row is plaintext now, but version 1 still holds ciphertext in the activity log.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(ciphertext, response.content.decode())
