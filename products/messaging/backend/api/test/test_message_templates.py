from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError

MINIMAL_DESIGN = {
    "counters": {"u_row": 1},
    "schemaVersion": 16,
    "body": {"id": "b", "rows": [{"id": "r", "cells": [1], "columns": [], "values": {}}], "values": {}},
}


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
        # templating is injected by the serializer default for legacy rows that never stored it
        assert template["content"] == {
            "templating": "liquid",
            "email": {"subject": "Test Subject", "text": "Test Body"},
        }
        assert template["type"] == "email"

    def test_retrieve_message_template(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/")
        assert response.status_code == status.HTTP_200_OK

        template = response.json()
        assert template["id"] == str(self.message_template.id)
        assert template["name"] == "Test Template"
        assert template["description"] == "Test description"
        assert template["content"] == {
            "templating": "liquid",
            "email": {"subject": "Test Subject", "text": "Test Body"},
        }
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

    def test_create_defaults_templating_to_liquid(self):
        """Authored HTML is full of braces (CSS, Liquid) — anything not explicitly
        'liquid' is hog-transpiled downstream, where '{' is syntax and compilation fails."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_templates/",
            data={
                "name": "No templating set",
                "content": {"email": {"subject": "Hi", "html": "<style>.a{color:red}</style><p>{{ greeting }}</p>"}},
                "type": "email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["content"]["templating"] == "liquid"

    def test_create_rejects_hog_templating(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_templates/",
            data={
                "name": "Hog attempt",
                "content": {"templating": "hog", "email": {"subject": "Hi", "html": "<p>Hi</p>"}},
                "type": "email",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "templating" in str(response.json())

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_create_with_design_only_renders_html_server_side(self, mock_render):
        mock_render.return_value = "<html><body>Rendered</body></html>"

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            data={
                "name": "Design-first template",
                "content": {"email": {"subject": "Hi", "design": MINIMAL_DESIGN}},
                "type": "email",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        mock_render.assert_called_once_with(MINIMAL_DESIGN)
        email = response.json()["content"]["email"]
        assert email["html"] == "<html><body>Rendered</body></html>"
        assert email["design"] == MINIMAL_DESIGN

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_create_with_design_and_html_keeps_submitted_html(self, mock_render):
        """The visual editor exports html from the design client-side and submits both —
        a present html is trusted, not re-rendered."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            data={
                "name": "Editor-saved template",
                "content": {"email": {"subject": "Hi", "html": "<p>Editor export</p>", "design": MINIMAL_DESIGN}},
                "type": "email",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        mock_render.assert_not_called()
        assert response.json()["content"]["email"]["html"] == "<p>Editor export</p>"

    @parameterized.expand(
        [
            ("render_failure", UnlayerRenderError("Unlayer returned 500"), "Rendering the design"),
            ("not_configured", UnlayerNotConfiguredError(), "not configured"),
        ]
    )
    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_create_with_design_render_error_returns_400(self, _name, side_effect, expected_message, mock_render):
        mock_render.side_effect = side_effect

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            data={
                "name": "Design-first template",
                "content": {"email": {"subject": "Hi", "design": MINIMAL_DESIGN}},
                "type": "email",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert expected_message in str(response.json())

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_update_with_design_only_renders_html_server_side(self, mock_render):
        mock_render.return_value = "<html><body>Re-rendered</body></html>"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/",
            data={"content": {"email": {"subject": "Updated", "design": MINIMAL_DESIGN}}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        mock_render.assert_called_once_with(MINIMAL_DESIGN)
        self.message_template.refresh_from_db()
        assert self.message_template.content["email"]["html"] == "<html><body>Re-rendered</body></html>"

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

    def _design_with_text(self) -> dict:
        return {
            "counters": {"u_row": 1, "u_column": 1, "u_content_text": 1},
            "schemaVersion": 16,
            "body": {
                "id": "body1",
                "rows": [
                    {
                        "id": "row1",
                        "cells": [1],
                        "columns": [
                            {
                                "id": "col1",
                                "contents": [{"id": "txt1", "type": "text", "values": {"text": "<p>Old</p>"}}],
                                "values": {},
                            }
                        ],
                        "values": {},
                    }
                ],
                "values": {},
            },
        }

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_design_patch_updates_one_block_and_rerenders(self, mock_render):
        mock_render.return_value = "<html>patched</html>"
        self.message_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.message_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>New</p>"}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.message_template.refresh_from_db()
        email = self.message_template.content["email"]
        assert email["design"]["body"]["rows"][0]["columns"][0]["contents"][0]["values"]["text"] == "<p>New</p>"
        # subject is preserved; html re-rendered from the patched design
        assert email["subject"] == "Hi"
        assert email["html"] == "<html>patched</html>"
        mock_render.assert_called_once()

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_design_patch_unknown_id_leaves_template_untouched(self, mock_render):
        mock_render.return_value = "<html>x</html>"
        original = self._design_with_text()
        self.message_template.content = {"email": {"subject": "Hi", "design": original}}
        self.message_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "nope", "patch": {"values": {}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.message_template.refresh_from_db()
        assert self.message_template.content["email"]["design"] == original
        mock_render.assert_not_called()

    def test_design_patch_without_design_returns_400(self):
        # self.message_template has no design in content.email
        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "no editable design" in str(response.json())

    def test_design_patch_empty_operations_returns_400(self):
        self.message_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.message_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_design_patch_missing_required_op_field_returns_400(self):
        self.message_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.message_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1"}]},  # missing patch
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_design_patch_requires_write_scope(self):
        self.message_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.message_template.save()
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.messaging.backend.api.message_templates.render_design_html")
    def test_design_patch_allows_write_scoped_personal_api_key(self, mock_render):
        # Regression: the design action must declare hog_flow:write so MCP / personal API key callers
        # aren't rejected as "action does not support personal API key access".
        mock_render.return_value = "<html>ok</html>"
        self.message_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.message_template.save()
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:write"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.message_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>Hi</p>"}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_design_patch_cannot_touch_other_teams_template(self):
        self.other_team_template.content = {"email": {"subject": "Hi", "design": self._design_with_text()}}
        self.other_team_template.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.other_team_template.id}/design/",
            data={"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {}}}]},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
