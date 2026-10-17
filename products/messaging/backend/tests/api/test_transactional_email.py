from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, ProjectSecretAPIKey, User
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.transactional_email_api import TransactionalEmailBurstThrottle
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset

PASSWORD_RESET_HASH = "v1:973d41bbe3fdca5c52bb951cd4b5fd7159ae630b56c8f3997cbb31afd1ea76fd"


@patch("products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.feature_enabled",
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
        self.template = self._template(key="password-reset")
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        self.url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/send/"
        self.send_email_url = f"/api/projects/{self.team.id}/messaging/send/email/"
        self.body = {
            "to": "user@example.com",
            "identifiers": {"distinct_id": "user-1"},
            "message_data": {"link": "https://example.com/reset", "nickname": None},
        }

    def _template(self, content: dict | None = None, key: str | None = None) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content=content
            or {"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
            key=key,
        )

    def _route(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/{path.format(id=self.template.id)}"

    def _send_request(self, addressed_by: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if addressed_by == "url_id":
            return self.url, body
        template = {"key": "password-reset"} if addressed_by == "key" else {"id": str(self.template.id)}
        return self.send_email_url, {**body, "template": template}

    def _workflow(self, hog_flow_id) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _cdp_accepts(self, mock_post: MagicMock, invocation_id: str = "invocation-1") -> None:
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": invocation_id})

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="transactional email",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    @parameterized.expand(
        [
            ("with_distinct_id", "url_id", {"distinct_id": "user-1"}, "user-1"),
            # Without a distinct_id the recipient's address is the person the send is tracked against.
            ("email_only", "url_id", None, "user@example.com"),
            ("by_key", "key", {"distinct_id": "user-1"}, "user-1"),
            ("by_id", "id", None, "user@example.com"),
        ]
    )
    def test_runs_the_templates_workflow_for_the_recipient(
        self, mock_post, _flag, capture, _name, addressed_by, identifiers, expected_distinct_id
    ):
        self._cdp_accepts(mock_post)
        url, body = self._send_request(
            addressed_by,
            {**self.body, "identifiers": identifiers}
            if identifiers
            else {k: v for k, v in self.body.items() if k != "identifiers"},
        )

        response = self._psak_client(["hog_flow:write"]).post(url, body, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        expected_response: dict[str, Any] = {"message_id": "invocation-1"}
        if addressed_by != "url_id":
            expected_response["warnings"] = []
        assert response.json() == expected_response
        assert capture.call_args.kwargs["properties"]["addressed_by"] == addressed_by
        assert mock_post.call_args.args[0].endswith(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}/transactional_email"
        )
        assert mock_post.call_args.kwargs["json"] == {
            "to": "user@example.com",
            "distinct_id": expected_distinct_id,
            "variables": {"link": "https://example.com/reset", "nickname": None},
        }

    @parameterized.expand(
        [
            (
                "send_with_write_scope",
                "post",
                "messaging_templates/{id}/send/",
                ["hog_flow:write"],
                status.HTTP_202_ACCEPTED,
            ),
            (
                "send_with_read_scope",
                "post",
                "messaging_templates/{id}/send/",
                ["hog_flow:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "send_email_with_write_scope",
                "post",
                "messaging/send/email/",
                ["hog_flow:write"],
                status.HTTP_202_ACCEPTED,
            ),
            (
                "send_email_with_read_scope",
                "post",
                "messaging/send/email/",
                ["hog_flow:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "retrieve_is_not_a_psak_action",
                "get",
                "messaging_templates/{id}/",
                ["hog_flow:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "make_transactional_is_not_a_psak_action",
                "post",
                "messaging_templates/{id}/make_transactional/",
                ["hog_flow:write"],
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    def test_project_secret_api_key_can_only_send(
        self, mock_post, _flag, _capture, _name, method, path, scopes, expected_status
    ):
        self._cdp_accepts(mock_post)

        response = getattr(self._psak_client(scopes), method)(
            self._route(path),
            {**self.body, "template": {"key": "password-reset"}} if method == "post" else None,
            format="json",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("not_transactional", "template_not_transactional"),
            ("workflow_archived", "transactional_email_paused"),
            ("category_turned_marketing", "marketing_template"),
            ("liquid_in_recipient", "invalid_recipient"),
        ]
    )
    def test_rejects_a_send_it_cannot_make(self, mock_post, _flag, _capture, case, expected_code):
        url, body = self.url, dict(self.body)
        if case == "not_transactional":
            url = f"/api/projects/{self.team.id}/messaging_templates/{self._template().id}/send/"
        elif case == "workflow_archived":
            archived = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}", {"status": "archived"}
            )
            assert archived.status_code == status.HTTP_200_OK, archived.json()
        elif case == "category_turned_marketing":
            category = MessageCategory.objects.create(
                team=self.team, key="account", name="Account", category_type=MessageCategoryType.TRANSACTIONAL
            )
            MessageTemplate.objects.filter(id=self.template.id).update(message_category=category)
            MessageCategory.objects.filter(id=category.id).update(category_type=MessageCategoryType.MARKETING)
        elif case == "liquid_in_recipient":
            body["to"] = "{{person.properties.email}}@example.com"

        response = self.client.post(url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert response.json()["type"] == "invalid_request"
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("unknown_key", {"key": "welcome"}, status.HTTP_404_NOT_FOUND, "template_not_found", "template__key"),
            ("unknown_id", {"id": str(uuid4())}, status.HTTP_404_NOT_FOUND, "template_not_found", "template__id"),
            ("deleted", {"key": "password-reset"}, status.HTTP_404_NOT_FOUND, "template_not_found", "template__key"),
            (
                "key_and_id",
                {"key": "password-reset", "id": str(uuid4())},
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "template",
            ),
            ("neither_key_nor_id", {}, status.HTTP_400_BAD_REQUEST, "invalid_request", "template"),
            (
                "hash_with_id",
                {"id": str(uuid4()), "hash": f"v1:{'0' * 64}"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "template",
            ),
            (
                "invalid_key",
                {"key": "password reset"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_template_key",
                "template__key",
            ),
            (
                "key_with_trailing_newline",
                {"key": "password-reset\n"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_template_key",
                "template__key",
            ),
        ]
    )
    def test_refuses_a_template_reference_it_cannot_send_with_what_to_fix(
        self, mock_post, _flag, _capture, case, template, expected_status, expected_code, expected_attr
    ):
        if case == "deleted":
            deleted = self.client.patch(self._route("messaging_templates/{id}/"), {"deleted": True}, format="json")
            assert deleted.status_code == status.HTTP_200_OK, deleted.json()

        response = self.client.post(self.send_email_url, {**self.body, "template": template}, format="json")

        assert response.status_code == expected_status, response.json()
        error = response.json()
        assert (error["code"], error["attr"]) == (expected_code, expected_attr)
        assert error["docs_url"] == f"https://posthog.com/docs/workflows/transactional-email-api#{expected_code}"
        assert error["why"] and error["fix"]
        mock_post.assert_not_called()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_both_send_routes_share_one_rate_limit_per_key(self, _rate_limit, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])

        with patch.object(TransactionalEmailBurstThrottle, "rate", "1/minute"):
            by_url_id = psak.post(self.url, self.body, format="json")
            by_key = psak.post(self.send_email_url, {**self.body, "template": {"key": "password-reset"}}, format="json")

        assert by_url_id.status_code == status.HTTP_202_ACCEPTED, by_url_id.json()
        assert by_key.status_code == status.HTTP_429_TOO_MANY_REQUESTS, by_key.json()

    @parameterized.expand(
        [
            ("timeout", requests.ReadTimeout()),
            ("cdp_api_error", MagicMock(status_code=500)),
        ]
    )
    def test_a_send_the_pipeline_does_not_confirm_is_unavailable(self, mock_post, _flag, _capture, _name, outcome):
        if isinstance(outcome, Exception):
            mock_post.side_effect = outcome
        else:
            mock_post.return_value = outcome

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "delivery_unavailable"

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

    def test_reports_quota_limited_teams(self, mock_post, _flag, _capture):
        mock_post.return_value = MagicMock(status_code=429, json=lambda: {"error": "quota_limited"})

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["code"] == "quota_limited"

    @parameterized.expand(
        [
            ("send", "messaging_templates/{id}/send/"),
            ("make_transactional", "messaging_templates/{id}/make_transactional/"),
            ("send_email", "messaging/send/email/"),
        ]
    )
    def test_is_hidden_while_the_flag_is_off(self, mock_post, flag, _capture, _name, path):
        flag.return_value = False

        response = self.client.post(
            self._route(path), {**self.body, "template": {"key": "password-reset"}}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_post.assert_not_called()

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
        self, mock_post, _flag, _capture, edit
    ):
        category = MessageCategory.objects.create(
            team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
        )
        body: dict[str, Any] = (
            {"message_category": str(category.id)} if edit == "marketing_category" else {"content": {}}
        )
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
    "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.feature_enabled",
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
            key="password-reset",
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
            ("send", "post", "messaging_templates/{id}/send/", {"to": "user@example.com"}),
            (
                "send_email",
                "post",
                "messaging/send/email/",
                {"to": "user@example.com", "template": {"key": "password-reset"}},
            ),
            (
                "update",
                "patch",
                "messaging_templates/{id}/",
                {"content": {"email": {"subject": "New", "html": "<p>New</p>"}}},
            ),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_send_or_change_it(self, mock_post, _flag, _name, method, path, body):
        url = f"/api/projects/{self.team.id}/{path.format(id=self.template.id)}"

        response = getattr(self.client, method)(url, body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("unchanged_content", False, {"content_hash": PASSWORD_RESET_HASH}),
            (
                "superseded_content",
                True,
                {"content_hash": "v1:" + "0" * 64, "superseded_content_hashes": [PASSWORD_RESET_HASH]},
            ),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_upload_to_it(
        self, mock_post, _flag, _name, if_not_superseded, stored_hashes
    ):
        MessageTemplate.objects.filter(id=self.template.id).update(managed_by="code", **stored_hashes)

        response = self.client.put(
            f"/api/projects/{self.team.id}/messaging_templates/by_key/password-reset/",
            {
                "name": "Password reset",
                "subject": "Reset your password",
                "html": "<p>Reset</p>",
                "source": {"repository": "github.com/example/other"},
                "if_not_superseded": if_not_superseded,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        self.template.refresh_from_db()
        assert self.template.source_repository is None

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
