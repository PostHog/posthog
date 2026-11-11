from posthog.test.base import APIBaseTest

from rest_framework import status


class TestWizardScanViewSet(APIBaseTest):
    def _payload(self) -> dict:
        return {
            "session_id": "onboarding-nextjs-2026-05-19T10:00:00Z",
            "program": "posthog-integration",
            "wizard_version": "2.0.0",
            "workspace_fingerprint": "a" * 64,
            "scanned_at": "2026-05-19T10:00:00Z",
            "tools": [{"kind": "Amplitude", "signals": [{"source": "npm", "name": "@amplitude/analytics-browser"}]}],
        }

    def _post(self) -> int:
        return self.client.post(
            f"/api/projects/{self.team.id}/wizard/scans/", self._payload(), format="json"
        ).status_code

    def test_records_a_scan_once_per_session(self) -> None:
        assert self._post() == status.HTTP_201_CREATED
        assert self._post() == status.HTTP_200_OK

    def test_requires_wizard_session_write_scope(self) -> None:
        token = self.create_personal_api_key_with_scopes(["wizard_session:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        assert self._post() == status.HTTP_403_FORBIDDEN
