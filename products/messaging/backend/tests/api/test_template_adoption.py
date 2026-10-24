from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret

from products.messaging.backend.models.message_template import MessageTemplate

DOCS_URL = "https://posthog.com/docs/workflows/transactional-email-api"


class TestTemplateAdoption(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.template = self._template_made_in_posthog("Welcome")

    def _template_made_in_posthog(self, name: str, key: str | None = None) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name=name,
            key=key,
            content={"email": {"subject": "Hello", "html": "<p>Hello</p>"}},
            type="email",
        )

    def _url(self, template: MessageTemplate) -> str:
        return f"/api/projects/{self.team.id}/messaging_templates/{template.id}/"

    def _adopt(self, key: Any, client: APIClient | None = None) -> Any:
        return (client or self.client).patch(self._url(self.template), {"key": key}, format="json")

    def _stored_key(self) -> str | None:
        return self.client.get(self._url(self.template)).json()["key"]

    def _personal_api_key_client(self) -> APIClient:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="MCP", user=self.user, secure_value=hash_key_value(token), scopes=["hog_flow:write"]
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_POSTHOG_CLIENT="mcp")
        return client

    def _project_secret_api_key_client(self) -> APIClient:
        token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="adoption",
            secure_value=hash_key_value(token),
            scopes=["hog_flow:write"],
            mask_value=f"{token[:4]}...{token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    @parameterized.expand([("session", None), ("personal_api_key", "_personal_api_key_client")])
    def test_gives_a_template_without_a_key_its_key_and_keeps_its_content(self, _name, client_factory):
        client = getattr(self, client_factory)() if client_factory else None

        response = self._adopt("welcome", client)

        assert response.status_code == status.HTTP_200_OK, response.json()
        adopted = response.json()
        assert (adopted["id"], adopted["key"], adopted["managed_by"]) == (str(self.template.id), "welcome", None)
        assert adopted["content"]["email"]["subject"] == "Hello"
        assert self._stored_key() == "welcome"

    def test_a_project_secret_api_key_cannot_adopt(self):
        response = self._adopt("welcome", self._project_secret_api_key_client())

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert self._stored_key() is None

    @parameterized.expand(
        [
            ("twice", "welcome", {"key": "welcome"}, "key_already_set", "welcome"),
            ("taken_key", None, {"key": "taken"}, "key_in_use", None),
            ("invalid_key", None, {"key": "wel come"}, "invalid_template_key", None),
            ("trailing_newline", None, {"key": "welcome\n"}, "invalid_template_key", None),
            ("null_key", None, {"key": None}, "invalid_template_key", None),
            ("key_with_other_fields", None, {"key": "welcome", "name": "Renamed"}, "invalid_request", None),
            (
                "changed_key_with_other_fields",
                "welcome",
                {"key": "other", "name": "Renamed"},
                "key_already_set",
                "welcome",
            ),
        ]
    )
    def test_refuses_a_key_it_cannot_set_and_says_how_to_fix_it(self, _name, adopted_key, body, code, stored_key):
        self._template_made_in_posthog("Taken", key="taken")
        if adopted_key:
            assert self._adopt(adopted_key).status_code == status.HTTP_200_OK

        response = self.client.patch(self._url(self.template), body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        refusal = response.json()
        assert (refusal["code"], refusal["attr"], refusal["docs_url"]) == (code, "key", f"{DOCS_URL}#{code}")
        assert refusal["detail"] and refusal["why"] and refusal["fix"]
        template = self.client.get(self._url(self.template)).json()
        assert (template["key"], template["name"]) == (stored_key, "Welcome")

    def test_a_form_save_that_sends_the_stored_key_back_keeps_working(self):
        assert self._adopt("welcome").status_code == status.HTTP_200_OK
        form = self.client.get(self._url(self.template)).json()

        response = self.client.patch(self._url(self.template), {**form, "name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["name"], response.json()["key"]) == ("Renamed", "welcome")
