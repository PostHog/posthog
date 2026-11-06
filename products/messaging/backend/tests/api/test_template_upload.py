from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, ProjectSecretAPIKey, Team
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.message_templates import (
    EMAIL_FROM_CODE_FLAG,
    TRANSACTIONAL_EMAIL_API_FLAG,
    TransactionalEmailBurstThrottle,
)
from products.messaging.backend.services import template_uploads
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
from products.workflows.backend.facade.models import HogFlow

WELCOME: dict[str, Any] = {
    "name": "Welcome",
    "subject": "Welcome, {{ variables.first_name }}",
    "html": "<p>Hi {{ variables.first_name }}</p>",
    "source": {"repository": "github.com/example/app", "path": "emails/welcome.html", "ref": "3f2c1ab"},
}
WELCOME_HASH = "v1:f74cd913f3aa2e5667a588f2865634e56693df77793ca594d18e9b5f89e3d2e6"
GREETING = {"name": "Welcome", "subject": "Grüße", "preheader": "Vorschau", "html": "<p>ä</p>\n", "text": "ä"}
GREETING_HASH = "v1:ff5293725c21e0f9b71918af66cf7b6e17b2021f250fe915f8426946b378c88d"


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTemplateUpload(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.sender = self._verified_sender("hello@example.com")
        set_default_email_sender_if_unset(self.team.id, self.sender.id)
        self.url = f"/api/projects/{self.team.id}/messaging_templates/by_key/welcome/"
        self.psak = self._psak_client(["hog_flow:write"])

    def _verified_sender(self, address: str) -> Integration:
        return Integration.objects.create(
            team=self.team, kind="email", integration_id=address, config={"verified": True}
        )

    def _psak_client(self, scopes: list[str], team: Team | None = None) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label=f"template upload {raw_token[:8]}",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _upload(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self.psak.put(self.url, body, format="json")
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.json()
        return response.json()

    def _template(self, template_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template_id}/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _workflow(self, hog_flow_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _sent_email(self, hog_flow_id: str) -> dict[str, Any]:
        return self._workflow(hog_flow_id)["actions"][1]["config"]["inputs"]["email"]["value"]

    def _superseded_hashes(self, template_id: str) -> list[str]:
        return MessageTemplate.objects.get(id=template_id).superseded_content_hashes or []

    def test_a_first_upload_creates_a_code_managed_transactional_template(self, _post: MagicMock, flag, _capture):
        flag.side_effect = lambda key, *_args, **_kwargs: key == EMAIL_FROM_CODE_FLAG
        response = self.psak.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        uploaded = response.json()
        assert uploaded["result"] == "created"
        assert uploaded["key"] == "welcome"
        assert uploaded["managed_by"] == "code"
        assert uploaded["content_hash"] == WELCOME_HASH
        assert uploaded["source"] == WELCOME["source"]
        template = self._template(uploaded["id"])
        assert template["key"] == "welcome"
        assert template["managed_by"] == "code"
        assert template["content_hash"] == WELCOME_HASH
        assert (template["source_repository"], template["source_path"], template["source_ref"]) == (
            "github.com/example/app",
            "emails/welcome.html",
            "3f2c1ab",
        )
        assert template["transactional_hog_flow_id"] == uploaded["transactional_hog_flow_id"]
        assert self._workflow(uploaded["transactional_hog_flow_id"])["status"] == "active"
        email = self._sent_email(uploaded["transactional_hog_flow_id"])
        assert (email["subject"], email["html"], email["from"]["integrationId"]) == (
            WELCOME["subject"],
            WELCOME["html"],
            self.sender.id,
        )

    @parameterized.expand(
        [
            ("same_text", WELCOME, WELCOME, WELCOME_HASH),
            ("other_line_endings", {**GREETING, "html": "<p>ä</p>\r\n"}, GREETING, GREETING_HASH),
        ]
    )
    def test_an_identical_upload_is_unchanged_and_writes_no_workflow_version(
        self, _post, _flag, _capture, _name, first_body, second_body, expected_hash
    ):
        first = self._upload(first_body)
        before = self._template(first["id"])

        with patch("products.messaging.backend.presentation.views.message_templates.publish_resource_edited") as edited:
            response = self.psak.put(self.url, {**second_body, "source": {"ref": "9e8d7c6"}}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["result"] == "unchanged"
        assert response.json()["content_hash"] == expected_hash
        kept_source = {**(first_body.get("source") or {"repository": None, "path": None}), "ref": "9e8d7c6"}
        assert response.json()["source"] == kept_source
        assert self._workflow(first["transactional_hog_flow_id"])["version"] == 1
        after = self._template(first["id"])
        assert {part: after[f"source_{part}"] for part in ("repository", "path", "ref")} == kept_source
        assert after["updated_at"] > before["updated_at"]
        assert (
            edited.call_args.kwargs["updated_at"] == MessageTemplate.objects.get(id=first["id"]).updated_at.isoformat()
        )

    def _edit_the_workflow_outside_the_template(
        self, hog_flow_id: str, field: str = "html", value: Any = "<p>Edited in the workflow</p>"
    ) -> None:
        workflow = HogFlow.objects.get(team=self.team, id=hog_flow_id)
        workflow.actions[1]["config"]["inputs"]["email"]["value"][field] = value
        HogFlow.objects.filter(team=self.team, id=hog_flow_id).update(actions=workflow.actions)

    @parameterized.expand(
        [
            (
                "stored_hash",
                lambda test, upload: MessageTemplate.objects.filter(id=upload["id"]).update(content_hash=GREETING_HASH),
            ),
            (
                "workflow_edited_outside_the_template",
                lambda test, upload: test._edit_the_workflow_outside_the_template(upload["transactional_hog_flow_id"]),
            ),
            (
                "recipient_edited_outside_the_template",
                lambda test, upload: test._edit_the_workflow_outside_the_template(
                    upload["transactional_hog_flow_id"], "to", {"email": "someone@example.com", "name": ""}
                ),
            ),
        ]
    )
    def test_an_upload_repairs_what_no_longer_matches_the_uploaded_content(self, _post, _flag, _capture, _name, drift):
        first = self._upload(WELCOME)
        drift(self, first)

        repaired = self._upload(WELCOME)

        assert (repaired["result"], repaired["content_hash"]) == ("updated", WELCOME_HASH)
        assert self._template(first["id"])["content_hash"] == WELCOME_HASH
        assert self._sent_email(first["transactional_hog_flow_id"])["html"] == WELCOME["html"]
        assert self._sent_email(first["transactional_hog_flow_id"])["to"]["email"] == "{{ event.properties.to | raw }}"

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_a_changed_upload_is_what_the_next_send_delivers(self, _reload, post: MagicMock, _flag, _capture):
        first = self._upload(WELCOME)
        post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})

        response = self.psak.put(self.url, GREETING, format="json")
        sent = self.psak.post(
            f"/api/projects/{self.team.id}/messaging_templates/{first['id']}/send/",
            {"to": "user@example.com", "message_data": {"first_name": "Jane"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["result"] == "updated"
        assert response.json()["content_hash"] == GREETING_HASH
        assert sent.status_code == status.HTTP_202_ACCEPTED, sent.json()
        hog_flow_id = response.json()["transactional_hog_flow_id"]
        assert hog_flow_id == first["transactional_hog_flow_id"]
        assert post.call_args.args[0].endswith(f"/hog_flows/{hog_flow_id}/transactional_email")
        assert post.call_args.kwargs["json"]["variables"] == {"first_name": "Jane"}
        email = self._sent_email(hog_flow_id)
        assert (email["subject"], email["preheader"], email["html"], email["text"]) == (
            "Grüße",
            "Vorschau",
            "<p>ä</p>\n",
            "ä",
        )
        assert self._workflow(hog_flow_id)["version"] == 2

    def test_an_upload_claims_an_adopted_template_and_keeps_its_id_sender_and_paused_workflow(
        self, _post, _flag, _capture
    ):
        other_sender = self._verified_sender("team@example.com")
        made_in_posthog = MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            content={
                "email": {
                    "subject": "Hello",
                    "html": "<p>Hello</p>",
                    "from": {"email": "hello@example.com", "name": "Example team"},
                    "replyTo": "replies@example.com",
                }
            },
            draft_content={"email": {"subject": "Hello draft", "html": "<p>Hello draft</p>"}},
            type="email",
        )
        hog_flow_id = make_transactional(
            self.team.id, made_in_posthog.id, user_id=self.user.id, from_integration_id=other_sender.id
        )
        paused = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}", {"status": "archived"})
        assert paused.status_code == status.HTTP_200_OK, paused.json()

        adopted = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{made_in_posthog.id}/", {"key": "welcome"}, format="json"
        )
        response = self.psak.put(self.url, WELCOME, format="json")

        assert adopted.status_code == status.HTTP_200_OK, adopted.json()
        assert (adopted.json()["key"], adopted.json()["managed_by"]) == ("welcome", None)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["result"], response.json()["id"]) == ("updated", str(made_in_posthog.id))
        assert response.json()["managed_by"] == "code"
        assert response.json()["transactional_hog_flow_id"] == str(hog_flow_id)
        workflow = self._workflow(str(hog_flow_id))
        assert workflow["status"] == "archived"
        email = self._sent_email(str(hog_flow_id))
        assert (email["subject"], email["from"], email["replyTo"]) == (
            WELCOME["subject"],
            {"integrationId": other_sender.id, "email": "hello@example.com", "name": "Example team"},
            "replies@example.com",
        )
        made_in_posthog.refresh_from_db()
        assert made_in_posthog.draft_content is None

    def _code_send_workflow_id(self, post: MagicMock) -> str:
        sent = self.psak.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {"to": "user@example.com", "template_key": "welcome", "subject": "Hi", "html": "<p>Hi</p>"},
            format="json",
        )
        assert sent.status_code == status.HTTP_202_ACCEPTED, sent.json()
        return post.call_args.args[0].split("/hog_flows/")[1].split("/")[0]

    @patch("products.messaging.backend.services.transactional_email.reload_hog_flows_on_workers")
    def test_code_sends_under_a_key_move_to_its_template_only_once_an_upload_claims_it(
        self, _reload, post: MagicMock, _flag, _capture
    ):
        post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})
        made_in_posthog = MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            content={"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
            type="email",
        )
        template_url = f"/api/projects/{self.team.id}/messaging_templates/{made_in_posthog.id}/"

        before_adoption = self._code_send_workflow_id(post)
        adopted = self.client.patch(template_url, {"key": "welcome"}, format="json")
        after_adoption = self._code_send_workflow_id(post)
        uploaded = self._upload(WELCOME)
        after_upload = self._code_send_workflow_id(post)
        released = self.client.patch(template_url, {"managed_by": "gui"}, format="json")
        after_release = self._code_send_workflow_id(post)

        assert adopted.status_code == status.HTTP_200_OK, adopted.json()
        assert released.status_code == status.HTTP_200_OK, released.json()
        template_workflow = uploaded["transactional_hog_flow_id"]
        assert template_workflow != before_adoption
        assert [after_adoption, after_upload, after_release] == [before_adoption, template_workflow, template_workflow]

    def _adopted_template_sending_from(self, sender: Integration) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            key="welcome",
            content={
                "email": {
                    "subject": "Hello",
                    "html": "<p>Hello</p>",
                    "from": {"integrationId": sender.id, "email": "team@example.com", "name": "Example team"},
                }
            },
            type="email",
        )

    def test_an_upload_makes_an_adopted_template_without_a_workflow_send_from_its_own_sender(
        self, _post, _flag, _capture
    ):
        own_sender = self._verified_sender("team@example.com")
        adopted = self._adopted_template_sending_from(own_sender)

        body = self._upload(WELCOME)

        assert (body["result"], body["id"]) == ("updated", str(adopted.id))
        assert self._sent_email(body["transactional_hog_flow_id"])["from"] == {
            "integrationId": own_sender.id,
            "email": "team@example.com",
            "name": "Example team",
        }

    @parameterized.expand(
        [
            ("new_template_without_a_verified_default", False, "The project has no verified default email sender."),
            ("adopted_template_with_an_unverified_sender", True, "The template's email sender isn't verified."),
        ]
    )
    def test_without_a_verified_sender_an_upload_names_the_sender_and_writes_nothing(
        self, _post, _flag, _capture, _name, adopted, expected_detail_start
    ):
        if adopted:
            unverified = Integration.objects.create(
                team=self.team, kind="email", integration_id="team@example.com", config={"verified": False}
            )
            self._adopted_template_sending_from(unverified)
        else:
            self.sender.config = {"verified": False}
            self.sender.save()

        response = self.psak.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "sender_unavailable"
        assert response.json()["detail"].startswith(expected_detail_start)
        stored = MessageTemplate.objects.filter(team=self.team)
        assert [(t.managed_by, t.transactional_hog_flow_id) for t in stored] == ([(None, None)] if adopted else [])

    @parameterized.expand(
        [
            ("invalid_key", "wel!come", WELCOME, "invalid_template_key", "key", "Use a key like `password-reset`."),
            (
                "missing_subject",
                "welcome",
                {"name": "Welcome", "html": "<p>Hi</p>"},
                "invalid_request",
                "subject",
                "Fix `subject` and upload again.",
            ),
            (
                "long_source_path",
                "welcome",
                WELCOME | {"source": {"path": "a" * 401}},
                "invalid_request",
                "source__path",
                "Fix `source__path` and upload again.",
            ),
            (
                "list_body",
                "welcome",
                [WELCOME],
                "invalid_request",
                None,
                "Send the body as a JSON object and upload again.",
            ),
        ]
    )
    def test_refuses_an_invalid_upload_with_the_field_to_fix(
        self, _post, _flag, _capture, _name, key, body, expected_code, expected_attr, expected_fix
    ):
        response = self.psak.put(f"/api/projects/{self.team.id}/messaging_templates/by_key/{key}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert (response.json()["attr"], response.json()["fix"]) == (expected_attr, expected_fix)
        assert response.json()["docs_url"].endswith(f"#{expected_code}")
        assert not MessageTemplate.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("read_scope", ["hog_flow:read"], False, {EMAIL_FROM_CODE_FLAG}, status.HTTP_403_FORBIDDEN),
            ("another_projects_key", ["hog_flow:write"], True, {EMAIL_FROM_CODE_FLAG}, status.HTTP_403_FORBIDDEN),
            (
                "only_the_transactional_email_api_flag",
                ["hog_flow:write"],
                False,
                {TRANSACTIONAL_EMAIL_API_FLAG},
                status.HTTP_404_NOT_FOUND,
            ),
        ]
    )
    def test_refuses_an_upload_it_does_not_allow(
        self, _post, flag, _capture, _name, scopes, other_project, enabled_flags, expected_status
    ):
        flag.side_effect = lambda key, *_args, **_kwargs: key in enabled_flags
        team = Team.objects.create(organization=self.organization, name="Other project") if other_project else None

        response = self._psak_client(scopes, team).put(self.url, WELCOME, format="json")

        assert response.status_code == expected_status, response.json()
        assert not MessageTemplate.objects.exists()

    def _code_send_under_the_key(self, post: MagicMock) -> str:
        post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})
        code_send = {
            "to": "user@example.com",
            "distinct_id": "user-1",
            "template_key": "welcome",
            "subject": "Hi",
            "html": "<p>Hi</p>",
        }
        sent = self.psak.post(f"/api/projects/{self.team.id}/messaging/send/email/", code_send, format="json")
        assert sent.status_code == status.HTTP_202_ACCEPTED, sent.json()
        return post.call_args.args[0].split("/hog_flows/")[1].split("/")[0]

    @parameterized.expand(
        [
            ("email_sending_paused", lambda: {"email_sending_paused_at": timezone.now()}),
            ("not_active", lambda: {"status": "draft"}),
        ]
    )
    def test_refuses_a_first_upload_under_a_key_whose_code_sends_are_paused(
        self, post: MagicMock, _flag, _capture, _name, pause
    ):
        key_workflow_id = self._code_send_under_the_key(post)
        HogFlow.objects.filter(team=self.team, id=key_workflow_id).update(**pause())

        response = self.psak.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "transactional_email_paused"
        assert f"`{key_workflow_id}`" in response.json()["detail"]
        assert not MessageTemplate.objects.exists()

    @parameterized.expand([("a_first_upload", False), ("an_upload_that_adopts_a_template", True)])
    def test_refuses_under_a_key_whose_workflow_the_member_cannot_edit(
        self, post: MagicMock, _flag, _capture, _name, adopts_a_template
    ):
        key_workflow_id = self._code_send_under_the_key(post)
        made_in_posthog = (
            MessageTemplate.objects.create(
                team=self.team,
                name="Welcome",
                key="welcome",
                type="email",
                content={"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
            )
            if adopts_a_template
            else None
        )
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team, resource="hog_flow", resource_id=key_workflow_id, access_level="viewer"
        )

        response = self.client.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert [
            (template.id, template.managed_by, template.content["email"]["subject"], template.transactional_hog_flow_id)
            for template in MessageTemplate.objects.all()
        ] == ([(made_in_posthog.id, None, "Hello", None)] if made_in_posthog else [])

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_uploads_leave_the_send_rate_limit_to_sends(self, _rate_limit, post: MagicMock, _flag, _capture):
        post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})

        with patch.object(TransactionalEmailBurstThrottle, "rate", "1/minute"):
            uploaded = self.psak.put(self.url, WELCOME, format="json")
            sent = self.psak.post(
                f"/api/projects/{self.team.id}/messaging_templates/{uploaded.json()['id']}/send/",
                {"to": "user@example.com"},
                format="json",
            )

        assert uploaded.status_code == status.HTTP_201_CREATED, uploaded.json()
        assert sent.status_code == status.HTTP_202_ACCEPTED, sent.json()

    def test_two_racing_first_uploads_end_with_one_template(self, _post, _flag, _capture):
        winner = self._upload(WELCOME)
        lookup = template_uploads.locked_template_with_key
        lookups: list[str] = []

        def misses_the_winner_once(team_id: int, key: str) -> MessageTemplate | None:
            lookups.append(key)
            return None if len(lookups) == 1 else lookup(team_id, key)

        with patch.object(template_uploads, "locked_template_with_key", side_effect=misses_the_winner_once):
            response = self.psak.put(self.url, GREETING, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["result"], response.json()["id"]) == ("updated", winner["id"])
        assert MessageTemplate.objects.filter(team=self.team, key="welcome").count() == 1

    def test_a_publish_moves_the_replaced_hash_to_the_superseded_list(self, _post, _flag, _capture):
        first = self._upload(WELCOME)
        released = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{first['id']}/", {"managed_by": "gui"}, format="json"
        )
        assert released.status_code == status.HTTP_200_OK, released.json()

        edited = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{first['id']}/",
            {"content": {"email": {"subject": "Edited in PostHog", "html": "<p>Edited</p>"}}},
            format="json",
        )
        edited_hash = edited.json()["content_hash"]
        superseded_after_edit = self._superseded_hashes(first["id"])
        rolled_back = self._upload(WELCOME)

        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert edited_hash not in (None, WELCOME_HASH)
        assert superseded_after_edit == [WELCOME_HASH]
        assert (rolled_back["result"], rolled_back["content_hash"]) == ("updated", WELCOME_HASH)
        assert self._superseded_hashes(first["id"]) == [edited_hash]

    @parameterized.expand(
        [
            ("superseded_content", WELCOME, "superseded", "Welcome aboard, {{ variables.first_name }}", "9e8d7c6", 2),
            ("new_content", GREETING, "updated", GREETING["subject"], "3f2c1ab", 3),
        ]
    )
    def test_an_upload_if_not_superseded_never_puts_replaced_content_back(
        self, _post, _flag, _capture, _name, body, expected_result, expected_subject, expected_ref, expected_version
    ):
        self._upload(WELCOME)
        newer = self._upload(
            {**WELCOME, "subject": "Welcome aboard, {{ variables.first_name }}", "source": {"ref": "9e8d7c6"}}
        )

        response = self.psak.put(
            self.url, {**body, "source": {"ref": "3f2c1ab"}, "if_not_superseded": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        uploaded = response.json()
        assert (uploaded["result"], uploaded["id"]) == (expected_result, newer["id"])
        template = self._template(newer["id"])
        assert uploaded["content_hash"] == template["content_hash"]
        assert (template["content"]["email"]["subject"], template["source_ref"]) == (expected_subject, expected_ref)
        assert self._workflow(newer["transactional_hog_flow_id"])["version"] == expected_version

    def _template_that_is(self, state: str) -> str | None:
        if state == "new":
            return None
        if state == "made_in_posthog":
            return str(
                MessageTemplate.objects.create(
                    team=self.team,
                    name="Welcome",
                    key="welcome",
                    type="email",
                    content={"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
                ).id
            )
        uploaded = self._upload(WELCOME)
        if state == "edited_in_posthog":
            for patch_body in (
                {"managed_by": "gui"},
                {"content": {"email": {"subject": "Edited", "html": "<p>E</p>"}}},
            ):
                edited = self.client.patch(
                    f"/api/projects/{self.team.id}/messaging_templates/{uploaded['id']}/", patch_body, format="json"
                )
                assert edited.status_code == status.HTTP_200_OK, edited.json()
        return uploaded["id"]

    @parameterized.expand(
        [
            ("made_in_posthog", "made_in_posthog", WELCOME, status.HTTP_409_CONFLICT, None),
            ("edited_in_posthog_over_superseded_content", "edited_in_posthog", WELCOME, status.HTTP_409_CONFLICT, None),
            ("managed_by_code", "managed_by_code", GREETING, status.HTTP_200_OK, "updated"),
            ("new_key", "new", WELCOME, status.HTTP_201_CREATED, "created"),
        ]
    )
    def test_an_upload_if_code_managed_refuses_a_template_edited_in_posthog(
        self, _post, _flag, _capture, _name, state, body, expected_status, expected_result
    ):
        template_id = self._template_that_is(state)
        templates_before = list(MessageTemplate.objects.values())
        workflows_before = list(HogFlow.objects.values("id", "version", "actions"))

        with patch("products.messaging.backend.presentation.views.message_templates.publish_resource_edited") as edited:
            response = self.psak.put(
                self.url, {**body, "if_code_managed": True, "if_not_superseded": True}, format="json"
            )

        assert response.status_code == expected_status, response.json()
        if expected_result is not None:
            assert response.json()["result"] == expected_result
            assert response.json()["managed_by"] == "code"
            assert template_id in (None, response.json()["id"])
            return
        refusal = response.json()
        assert (refusal["code"], refusal["attr"]) == ("template_edited_in_posthog", "if_code_managed")
        assert "if_code_managed" in refusal["fix"]
        assert list(MessageTemplate.objects.values()) == templates_before
        assert list(HogFlow.objects.values("id", "version", "actions")) == workflows_before
        edited.assert_not_called()
