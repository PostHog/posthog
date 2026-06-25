from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestMmmApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self._prefix_override = override_settings(MARKETING_MMM_S3_PREFIX=f"marketing_mmm_test_{uuid4().hex}")
        self._prefix_override.enable()

    def tearDown(self) -> None:
        self._prefix_override.disable()
        super().tearDown()

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.pk}/marketing_analytics/{action}/"

    @parameterized.expand(["mmm_runs", "mmm_calibrations"])
    def test_non_staff_is_denied(self, action: str) -> None:
        # Staff is the server-side boundary while MMM is in development; the feature flag only gates UI.
        self.user.is_staff = False
        self.user.save()
        response = self.client.get(self._url(action))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_runs_empty_for_fresh_project(self) -> None:
        # No run objects for this team: the glob matches nothing and degrades to an empty list.
        response = self.client.get(self._url("mmm_runs"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}

    def test_calibrations_round_trip(self) -> None:
        # POST validates + persists; GET reads back the stored calibration (the only write path in the POC).
        post = self.client.post(
            self._url("mmm_calibrations"),
            {
                "calibrations": [
                    {"channel": "google", "lift_pct": 12.5, "ci_low": 8.0, "ci_high": 17.0, "source": "manual"}
                ]
            },
            format="json",
        )
        assert post.status_code == status.HTTP_200_OK
        get = self.client.get(self._url("mmm_calibrations"))
        assert get.status_code == status.HTTP_200_OK
        calibrations = get.json()["calibrations"]
        assert len(calibrations) == 1
        assert calibrations[0]["channel"] == "google"
        assert calibrations[0]["lift_pct"] == 12.5

    def _scoped_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="mmm", user=self.user, scopes=scopes, secure_value=hash_key_value(value))
        return value

    def test_calibrations_post_requires_write_scope(self) -> None:
        # The POST replaces the calibration priors, so it must require marketing_analytics:write. A token
        # scoped only to :read can read the calibrations but must not be able to overwrite them — the staff
        # gate is a separate check and does not stand in for the correct scope.
        body = {"calibrations": [{"channel": "google", "lift_pct": 12.5, "ci_low": 8.0, "ci_high": 17.0}]}
        self.client.logout()  # force the personal-API-key path; session auth bypasses scope checks

        read_key = self._scoped_key(["marketing_analytics:read"])
        denied = self.client.post(
            self._url("mmm_calibrations"), body, format="json", HTTP_AUTHORIZATION=f"Bearer {read_key}"
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        readable = self.client.get(self._url("mmm_calibrations"), HTTP_AUTHORIZATION=f"Bearer {read_key}")
        assert readable.status_code == status.HTTP_200_OK

        write_key = self._scoped_key(["marketing_analytics:write"])
        allowed = self.client.post(
            self._url("mmm_calibrations"), body, format="json", HTTP_AUTHORIZATION=f"Bearer {write_key}"
        )
        assert allowed.status_code == status.HTTP_200_OK

    def test_calibrations_rejects_inverted_interval(self) -> None:
        response = self.client.post(
            self._url("mmm_calibrations"),
            {"calibrations": [{"channel": "google", "lift_pct": 5.0, "ci_low": 9.0, "ci_high": 2.0}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_503_when_scratch_bucket_unconfigured_on_cloud(self) -> None:
        # On Cloud, an unset MARKETING_MMM_S3_BUCKET falls back to OBJECT_STORAGE_BUCKET; equality means
        # the env is missing, so the read endpoints must fail loudly instead of reading the wrong bucket.
        with override_settings(CLOUD_DEPLOYMENT="US", MARKETING_MMM_S3_BUCKET="b", OBJECT_STORAGE_BUCKET="b"):
            response = self.client.get(self._url("mmm_runs"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "MARKETING_MMM_S3_BUCKET" in response.json()["detail"]
