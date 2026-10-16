from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.services import template_uploads
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset

WELCOME: dict[str, Any] = {
    "name": "Welcome",
    "subject": "Welcome, {{ variables.first_name }}",
    "html": "<p>Hi {{ variables.first_name }}</p>",
    "source": {"repository": "github.com/example/app", "path": "emails/welcome.html", "ref": "3f2c1ab"},
}
WELCOME_HASH = "v1:f74cd913f3aa2e5667a588f2865634e56693df77793ca594d18e9b5f89e3d2e6"
# HTML files end with a newline. The upload stores it, so the stored hash matches the hash of the file.
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

    def test_a_first_upload_creates_a_code_managed_transactional_template(self, _post: MagicMock, _flag, _capture):
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

    def test_an_identical_upload_is_unchanged_and_writes_no_workflow_version(self, _post, _flag, _capture):
        first = self._upload(WELCOME)

        response = self.psak.put(self.url, {**WELCOME, "source": {"ref": "9e8d7c6"}}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["result"] == "unchanged"
        assert response.json()["content_hash"] == WELCOME_HASH
        assert response.json()["source"] == {**WELCOME["source"], "ref": "9e8d7c6"}
        assert self._workflow(first["transactional_hog_flow_id"])["version"] == 1

    @patch("products.messaging.backend.services.transactional_email.reload_hog_flows_on_workers")
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

    def test_an_upload_claims_a_keyed_template_and_keeps_its_sender_and_paused_workflow(self, _post, _flag, _capture):
        other_sender = self._verified_sender("team@example.com")
        adopted = MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            key="welcome",
            content={"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
            type="email",
        )
        hog_flow_id = make_transactional(
            self.team.id, adopted.id, user_id=self.user.id, from_integration_id=other_sender.id
        )
        paused = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}", {"status": "archived"})
        assert paused.status_code == status.HTTP_200_OK, paused.json()

        response = self.client.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["result"], response.json()["id"]) == ("updated", str(adopted.id))
        assert response.json()["managed_by"] == "code"
        workflow = self._workflow(str(hog_flow_id))
        assert workflow["status"] == "archived"
        assert self._sent_email(str(hog_flow_id))["from"]["integrationId"] == other_sender.id

    def test_without_a_verified_default_sender_an_upload_writes_nothing(self, _post, _flag, _capture):
        self.sender.config = {"verified": False}
        self.sender.save()

        response = self.psak.put(self.url, WELCOME, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "sender_unavailable"
        assert not MessageTemplate.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("invalid_key", "wel!come", WELCOME, "invalid_template_key", "key"),
            ("missing_subject", "welcome", {"name": "Welcome", "html": "<p>Hi</p>"}, "invalid_request", "subject"),
            (
                "long_source_path",
                "welcome",
                {**WELCOME, "source": {"path": "a" * 401}},
                "invalid_request",
                "source__path",
            ),
        ]
    )
    def test_refuses_an_invalid_upload_with_the_field_to_fix(
        self, _post, _flag, _capture, _name, key, body, expected_code, expected_attr
    ):
        response = self.psak.put(f"/api/projects/{self.team.id}/messaging_templates/by_key/{key}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert response.json()["attr"] == expected_attr
        assert response.json()["docs_url"].endswith(f"#{expected_code}")
        assert not MessageTemplate.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("read_scope", ["hog_flow:read"], False, True, status.HTTP_403_FORBIDDEN),
            ("another_projects_key", ["hog_flow:write"], True, True, status.HTTP_403_FORBIDDEN),
            ("flag_off", ["hog_flow:write"], False, False, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_refuses_an_upload_it_does_not_allow(
        self, _post, flag, _capture, _name, scopes, other_project, flag_on, expected_status
    ):
        flag.return_value = flag_on
        team = Team.objects.create(organization=self.organization, name="Other project") if other_project else None

        response = self._psak_client(scopes, team).put(self.url, WELCOME, format="json")

        assert response.status_code == expected_status, response.json()
        assert not MessageTemplate.objects.exists()

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
            ("current", None, status.HTTP_202_ACCEPTED, []),
            ("superseded", WELCOME_HASH, status.HTTP_202_ACCEPTED, ["template_superseded"]),
            ("outdated", f"v1:{'0' * 64}", status.HTTP_409_CONFLICT, None),
        ]
    )
    @patch("products.messaging.backend.services.transactional_email.reload_hog_flows_on_workers")
    def test_a_send_by_key_with_a_hash_only_ever_sends_the_published_content(
        self, hash_state, sent_hash, expected_status, expected_warnings, _reload, post: MagicMock, _flag, capture
    ):
        post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})
        self._upload(WELCOME)
        published = self._upload({**WELCOME, "subject": "Welcome aboard, {{ variables.first_name }}"})
        hog_flow_id = published["transactional_hog_flow_id"]

        response = self.psak.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {
                "template": {"key": "welcome", "hash": sent_hash or published["content_hash"]},
                "to": "jane@example.com",
                "message_data": {"first_name": "Jane"},
            },
            format="json",
        )

        assert response.status_code == expected_status, response.json()
        assert capture.call_args.kwargs["properties"]["hash_state"] == hash_state
        if expected_warnings is None:
            assert response.json()["code"] == "template_outdated"
            post.assert_not_called()
        else:
            assert [warning["code"] for warning in response.json()["warnings"]] == expected_warnings
            assert post.call_args.args[0].endswith(f"/hog_flows/{hog_flow_id}/transactional_email")
        assert self._template(published["id"])["content_hash"] == published["content_hash"]
        assert self._sent_email(hog_flow_id)["subject"] == "Welcome aboard, {{ variables.first_name }}"
        assert self._workflow(hog_flow_id)["version"] == 2
