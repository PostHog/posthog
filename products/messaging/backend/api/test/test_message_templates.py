from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate


class TestMessageTemplatesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.message_template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test description",
            content={"email": {"subject": "Test Subject", "text": "Test Body"}},
            type="email",
        )

        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_team_template = MessageTemplate.objects.create(
            team=self.other_team,
            name="Other Team Template",
            description="Other team template description",
            content={"email": {"subject": "Other Team Subject", "text": "Other Team Body"}},
            type="email",
        )

    def test_list_message_templates(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/")
        assert response.status_code == status.HTTP_200_OK

        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        template = response_data["results"][0]
        assert template["id"] == str(self.message_template.id)
        assert template["name"] == "Test Template"
        assert template["description"] == "Test description"
        assert template["content"] == {"email": {"subject": "Test Subject", "text": "Test Body"}}
        assert template["type"] == "email"

    def test_retrieve_message_template(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/")
        assert response.status_code == status.HTTP_200_OK

        template = response.json()
        assert template["id"] == str(self.message_template.id)
        assert template["name"] == "Test Template"
        assert template["description"] == "Test description"
        assert template["content"] == {"email": {"subject": "Test Subject", "text": "Test Body"}}
        assert template["type"] == "email"

    def test_cannot_access_other_teams_templates(self):
        response = self.client.get(f"/api/environments/{self.other_team.id}/messaging_templates/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_templates/{self.other_team_template.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_authentication_required(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_operation_not_allowed(self):
        response = self.client.delete(
            f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/"
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_create_email_template_without_subject_fails(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_templates/",
            data={
                "name": "No Subject Template",
                "content": {"email": {"html": "<p>Hello</p>"}},
                "type": "email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_email_template_with_subject_succeeds(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_templates/",
            data={
                "name": "Valid Template",
                "content": {"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
                "type": "email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "Valid Template"
        assert response.json()["content"]["email"]["subject"] == "Hello"

    def test_create_email_template_without_email_content_succeeds(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_templates/",
            data={
                "name": "No Email Content",
                "type": "email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_cannot_bind_template_to_other_teams_message_category_via_patch(self):
        """Regression: PATCH must not accept a MessageCategory pk owned by a different team."""
        foreign_category = MessageCategory.objects.create(team=self.other_team, key="foreign-key", name="Foreign")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/",
            data={"message_category": str(foreign_category.id)},
            format="json",
        )

        # TeamScopedPrimaryKeyRelatedField restricts the queryset to the caller's
        # team, so the foreign id is unknown — DRF returns 400.
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.message_template.refresh_from_db()
        assert self.message_template.message_category_id is None

    @parameterized.expand(
        [
            ("list_with_read_scope", ["hog_flow:read"], "get", None, status.HTTP_200_OK),
            ("retrieve_with_read_scope", ["hog_flow:read"], "get", "detail", status.HTTP_200_OK),
            ("create_with_write_scope", ["hog_flow:write"], "post", None, status.HTTP_201_CREATED),
            ("update_with_write_scope", ["hog_flow:write"], "patch", "detail", status.HTTP_200_OK),
            ("create_with_read_scope_forbidden", ["hog_flow:read"], "post", None, status.HTTP_403_FORBIDDEN),
            ("update_with_read_scope_forbidden", ["hog_flow:read"], "patch", "detail", status.HTTP_403_FORBIDDEN),
            ("list_with_unrelated_scope_forbidden", ["insight:read"], "get", None, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_personal_api_key_scope_enforcement(self, _name, scopes, method, target, expected_status):
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        base_url = f"/api/projects/{self.team.id}/messaging_templates/"
        url = f"{base_url}{self.message_template.id}/" if target == "detail" else base_url
        data = (
            {
                "name": "API key template",
                "content": {"email": {"subject": "Hi", "html": "<p>Hi</p>"}},
                "type": "email",
            }
            if method in ("post", "patch")
            else None
        )

        response = getattr(self.client, method)(url, data=data, format="json")
        assert response.status_code == expected_status, response.json()

    def test_update_replaces_content_wholesale(self):
        """The content JSONField is replaced as a unit on update, never deep-merged —
        a payload without design makes the submitted html canonical."""
        self.message_template.content = {
            "email": {"subject": "Old", "html": "<p>Old</p>", "design": {"body": {"rows": []}}}
        }
        self.message_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/",
            data={"content": {"email": {"subject": "New", "html": "<p>New</p>"}}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.message_template.refresh_from_db()
        assert self.message_template.content["email"] == {"subject": "New", "html": "<p>New</p>"}

    def test_personal_api_key_cannot_access_other_teams_template(self):
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{self.other_team_template.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_can_bind_template_to_own_teams_message_category(self):
        own_category = MessageCategory.objects.create(team=self.team, key="own-key", name="Own")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/",
            data={"message_category": str(own_category.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        self.message_template.refresh_from_db()
        assert self.message_template.message_category_id == own_category.id
