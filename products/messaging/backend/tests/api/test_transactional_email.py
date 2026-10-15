from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.integration import Integration

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmail(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, self.sender.id)
        self.template = self._template()
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )

    def _template(self, content: dict | None = None) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content=content
            or {"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
        )

    def _workflow(self, hog_flow_id) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    @parameterized.expand(
        [
            ("update", "", {"name": "Reset"}),
            (
                "design",
                "design/",
                {"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>New</p>"}}}]},
            ),
        ]
    )
    @patch(
        "products.messaging.backend.presentation.views.message_templates.render_design_html",
        return_value="<p>New</p>",
    )
    def test_a_deleted_workflow_unlinks_the_template_until_it_is_made_transactional_again(
        self, _name, suffix, body, _render, mock_post, _flag, _capture
    ):
        design = {
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
            }
        }
        MessageTemplate.objects.filter(id=self.template.id).update(
            content={"email": {**self.template.content["email"], "design": design}}
        )
        deleted = self.client.delete(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        template_url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/"

        edited = self.client.patch(f"{template_url}{suffix}", body, format="json")
        remade = self.client.post(f"{template_url}make_transactional/", {}, format="json")

        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert edited.json()["transactional_hog_flow_id"] is None
        assert remade.json()["transactional_hog_flow_id"] not in (None, str(self.hog_flow_id))

    def test_is_hidden_while_the_flag_is_off(self, mock_post, flag, _capture):
        flag.return_value = False

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/make_transactional/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_making_a_template_transactional_creates_its_workflow_once(self, mock_post, _flag, _capture):
        template = self._template()
        url = f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/"

        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")

        assert first.status_code == status.HTTP_200_OK, first.json()
        hog_flow_id = first.json()["transactional_hog_flow_id"]
        assert second.json()["transactional_hog_flow_id"] == hog_flow_id
        workflow = self._workflow(hog_flow_id)
        assert workflow["status"] == "active"
        assert workflow["origin_product"] == "transactional_emails"
        assert workflow["trigger"] == {"type": "api"}
        listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows?type=transactional_email").json()
        assert {flow["id"] for flow in listed["results"]} == {str(self.hog_flow_id), hog_flow_id}

    @parameterized.expand(
        [
            ("marketing_template", "marketing_template"),
            ("deleted_marketing_category", "marketing_template"),
            ("template_without_subject", "template_not_sendable"),
            ("template_without_body", "template_not_sendable"),
            ("unverified_sender", "sender_unavailable"),
        ]
    )
    def test_rejects_making_a_template_transactional_it_cannot_send(
        self, mock_post, _flag, _capture, case, expected_code
    ):
        template = self._template()
        if case in ("marketing_template", "deleted_marketing_category"):
            template.message_category = MessageCategory.objects.create(
                team=self.team,
                key="news",
                name="News",
                category_type=MessageCategoryType.MARKETING,
                deleted=case == "deleted_marketing_category",
            )
        elif case == "template_without_subject":
            template.content = {"email": {"html": "<p>Hi</p>"}}
        elif case == "template_without_body":
            template.content = {"email": {"subject": "Hi"}}
        elif case == "unverified_sender":
            self.sender.config = {"verified": False}
            self.sender.save()
        template.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/", {}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    @patch("products.messaging.backend.services.transactional_email.reload_hog_flows_on_workers")
    def test_saving_a_transactional_template_writes_a_new_workflow_version(self, reload, mock_post, _flag, _capture):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/",
                {"content": {"email": {"subject": "A new subject", "html": "<p>New</p>"}}},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        # Workers reload once the new version is committed, not only from inside the transaction.
        reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(self.hog_flow_id)])
        workflow = self._workflow(self.hog_flow_id)
        assert workflow["version"] == 2
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        assert (email["subject"], email["html"]) == ("A new subject", "<p>New</p>")

    @parameterized.expand([("marketing_category",), ("no_email_content",)])
    def test_a_template_whose_workflow_was_deleted_takes_edits_it_could_not_send_with(
        self, _name, mock_post, _flag, _capture
    ):
        category = MessageCategory.objects.create(
            team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
        )
        body = {"message_category": str(category.id)} if _name == "marketing_category" else {"content": {}}
        self.client.delete(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", body, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["transactional_hog_flow_id"] is None

    def test_deleting_a_transactional_template_succeeds(self, mock_post, _flag, _capture):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", {"deleted": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.template.refresh_from_db()
        assert self.template.deleted

    def test_rejects_an_update_that_would_stop_a_transactional_template_sending(self, mock_post, _flag, _capture):
        category = MessageCategory.objects.create(
            team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/",
            {"message_category": str(category.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "marketing_template"
        self.template.refresh_from_db()
        assert self.template.message_category_id is None
        assert self._workflow(self.hog_flow_id)["version"] == 1


@pytest.mark.ee
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmailWorkflowAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        self.template = MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content={"email": {"subject": "Reset your password", "html": "<p>Reset</p>"}},
            type="email",
        )
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        self._login_member("member@example.com", {str(self.hog_flow_id): "none"})

    def _login_member(self, email: str, levels: dict[str | None, str]) -> None:
        member = User.objects.create_and_join(self.organization, email, "testtest")
        membership_id = OrganizationMembership.objects.get(user=member, organization=self.organization).id
        for resource_id, access_level in levels.items():
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                resource_id=resource_id,
                access_level=access_level,
                organization_member_id=membership_id,
            )
        self.client.force_login(member)

    @parameterized.expand(
        [
            ("update", "patch", "", {"content": {"email": {"subject": "New", "html": "<p>New</p>"}}}),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_change_it(self, mock_post, _flag, _name, method, suffix, body):
        url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/{suffix}"

        response = getattr(self.client, method)(url, body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    @parameterized.expand([("unlinked", None), ("linked_to_a_deleted_workflow", uuid4())])
    def test_editor_access_to_one_workflow_cannot_create_another(self, mock_post, _flag, _name, linked_hog_flow_id):
        self._login_member("viewer@example.com", {None: "viewer", str(self.hog_flow_id): "editor"})
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": "<p>Hi</p>"}},
            type="email",
            transactional_hog_flow_id=linked_hog_flow_id,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/", {}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        template.refresh_from_db()
        assert template.transactional_hog_flow_id == linked_hog_flow_id
