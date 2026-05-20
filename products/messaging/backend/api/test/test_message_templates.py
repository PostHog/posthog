from posthog.test.base import APIBaseTest

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
