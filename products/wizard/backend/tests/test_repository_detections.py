from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import PersonalAPIKey
from posthog.models.scoping import team_scope
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.wizard.backend.models import WizardRepositoryDetection
from products.wizard.backend.presentation.serializers import (
    MAX_DETECTED_PROJECTS,
    UpsertWizardRepositoryDetectionRequestSerializer,
)


def _report(**overrides) -> dict:
    report = {
        "repo_type": "monorepo",
        "projects": [
            {
                "path": "apps/web",
                "framework": "Next.js",
                "variant": "nextjs",
                "has_posthog": True,
                "instrumentable": True,
            },
            {
                "path": "apps/mobile",
                "framework": "React Native",
                "variant": None,
                "has_posthog": False,
                "instrumentable": False,
                "reason": "Source-map upload isn't supported for this stack yet",
            },
        ],
    }
    report.update(overrides)
    return report


class TestWizardRepositoryDetectionViewSet(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/wizard/repository_detections/"

    def _payload(self, **overrides) -> dict:
        payload = {
            "repository": "posthog/posthog",
            "kind": "error-tracking-source-maps",
            "report": _report(),
        }
        payload.update(overrides)
        return payload

    def _authenticate_personal_api_key(self, scopes: list[str]) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Detection test key",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_repost_same_repository_and_kind_upserts(self):
        first = self.client.post(self._url(), self._payload(), format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json()["report"]["repo_type"], "monorepo")

        second = self.client.post(
            self._url(),
            self._payload(report=_report(repo_type="single")),
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json()["report"]["repo_type"], "single")

        with team_scope(self.team.id):
            self.assertEqual(WizardRepositoryDetection.objects.count(), 1)
            detection = WizardRepositoryDetection.objects.get()
        assert detection.report is not None
        self.assertEqual(detection.report["repo_type"], "single")
        self.assertEqual(detection.created_by, self.user)

    def test_error_push_replaces_report(self):
        self.client.post(self._url(), self._payload(), format="json")
        response = self.client.post(
            self._url(),
            self._payload(report=None, error={"type": "no-manifests", "message": "No project manifests found"}),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        with team_scope(self.team.id):
            detection = WizardRepositoryDetection.objects.get()
        self.assertIsNone(detection.report)
        assert detection.error is not None
        self.assertEqual(detection.error["type"], "no-manifests")

    @parameterized.expand(
        [
            ("write_scope_can_post", ["wizard_session:write"], status.HTTP_201_CREATED),
            ("unrelated_scope_cannot_post", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_create_scope_enforcement(self, _name, scopes, expected_status):
        self._authenticate_personal_api_key(scopes)
        response = self.client.post(self._url(), self._payload(), format="json")
        self.assertEqual(response.status_code, expected_status)

    def test_invalid_payload_rejected(self):
        response = self.client.post(self._url(), self._payload(report=None), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestUpsertWizardRepositoryDetectionValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("report_only", {"report": _report()}, True),
            ("error_only", {"error": {"message": "agent crashed"}}, True),
            ("neither_report_nor_error", {}, False),
            ("both_report_and_error", {"report": _report(), "error": {"message": "boom"}}, False),
            ("unknown_repo_type", {"report": _report(repo_type="multirepo")}, False),
            ("project_missing_required_fields", {"report": _report(projects=[{"path": "."}])}, False),
            (
                "too_many_projects",
                {
                    "report": _report(
                        projects=[
                            {"path": f"p{i}", "framework": "Node.js", "has_posthog": False, "instrumentable": False}
                            for i in range(MAX_DETECTED_PROJECTS + 1)
                        ]
                    )
                },
                False,
            ),
            ("error_missing_message", {"error": {"type": "agent-error"}}, False),
        ]
    )
    def test_exactly_one_of_report_or_error(self, _name, body_part, expected_valid):
        serializer = UpsertWizardRepositoryDetectionRequestSerializer(
            data={"repository": "posthog/posthog", "kind": "error-tracking-source-maps", **body_part}
        )
        self.assertEqual(serializer.is_valid(), expected_valid)

    @parameterized.expand(
        [
            ("org_and_repo", "posthog/posthog", "posthog/posthog"),
            ("surrounding_whitespace_stripped", "  posthog/posthog  ", "posthog/posthog"),
            ("no_slash", "posthog", None),
            ("trailing_slash", "posthog/posthog/", None),
            ("empty_org", "/posthog", None),
            ("nested_path", "posthog/posthog/frontend", None),
        ]
    )
    def test_repository_must_be_org_slash_repo(self, _name, repository, expected):
        # repository is half the idempotency anchor under a unique constraint, so a value the shape
        # check lets through splits into a second row instead of replacing the first.
        serializer = UpsertWizardRepositoryDetectionRequestSerializer(
            data={"repository": repository, "kind": "error-tracking-source-maps", "report": _report()}
        )
        self.assertEqual(serializer.is_valid(), expected is not None)
        if expected is not None:
            self.assertEqual(serializer.validated_data.repository, expected)
