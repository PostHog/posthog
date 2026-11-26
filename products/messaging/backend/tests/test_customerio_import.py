from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import ImportStepBlocked


class TestCustomerIOGlobalUnsubscribes(BaseTest):
    @patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
    @patch("products.messaging.backend.services.customerio_client.requests.Session.request")
    def test_everyone_customerio_counts_as_unsubscribed_is_opted_out(
        self, request: MagicMock, _start: MagicMock
    ) -> None:
        people = {"bool@example.com": "true", "number@example.com": "1", "stays@example.com": "false"}

        def answer(method: str, url: str, json: dict[str, Any] | None, **_: Any) -> MagicMock:
            response = MagicMock(status_code=200)
            body: dict[str, Any] = {"topics": []}
            if url.endswith("/customers"):
                assert json is not None
                # Customer.io compares values as text, so true doesn't find 1.
                values = {str(part["attribute"]["value"]).lower() for part in json["filter"]["or"]}
                found = [email for email, value in people.items() if value in values]
                body = {"identifiers": [{"id": None, "email": email} for email in found], "next": ""}
            response.json.return_value = body
            return response

        request.side_effect = answer
        run = runs.start_run(self.team.id, "customerio", ["opt_outs"], "app-key", self.user.id)

        runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)

        opted_out = MessageRecipientPreference.objects.filter(team_id=self.team.id)
        assert {row.identifier for row in opted_out} == {"bool@example.com", "number@example.com"}


PROVIDER_FLAGS_PATH = "products.messaging.backend.facade.provider_imports.feature_enabled_or_false"
TRANSACTIONAL_MESSAGES = [
    {"id": 1, "name": "All uncategorized email messages", "send_to_unsubscribed": True},
    {"id": 7, "name": "Password reset", "send_to_unsubscribed": True, "hide_message_body": True},
    {"id": 8, "name": "Subject only", "send_to_unsubscribed": True},
]
TRANSACTIONAL_CONTENTS: dict[str, list[dict[str, Any]]] = {
    "1": [{"id": 1, "language": "", "subject": "", "body": "", "headers": "[]"}],
    "7": [
        {
            "id": 70,
            "language": "",
            "subject": "Reset your password, {{customer.first_name | default: 'there'}}",
            "body": "<html><body>{% for step in trigger.steps %}<p>{{step}}</p>{% endfor %}"
            '<a href="{{trigger.reset_url}}">Reset</a></body></html>',
            "body_plain": "Reset here: {{trigger.reset_url}}",
            "headers": "[]",
        },
        {
            "id": 71,
            "language": "fr",
            "subject": "Réinitialisez votre mot de passe",
            "body": '<html><body><a href="{{trigger.reset_url}}">Réinitialiser</a></body></html>',
            "headers": "[]",
        },
    ],
    "8": [{"id": 80, "language": "", "subject": "No body yet", "body": "", "headers": "[]"}],
}


def _customerio_answer(method: str, url: str, **_: Any) -> MagicMock:
    response = MagicMock(status_code=200)
    path = url.split("/v1", 1)[1]
    if path == "/transactional":
        body: dict[str, Any] = {"messages": TRANSACTIONAL_MESSAGES}
    elif path.startswith("/transactional/"):
        body = {"contents": TRANSACTIONAL_CONTENTS[path.split("/")[2]]}
    elif path == "/sender_identities":
        body = {"sender_identities": [], "next": ""}
    else:
        body = {"topics": [], "snippets": []}
    response.json.return_value = body
    return response


class TestCustomerIOTransactionalMessages(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for target, options in (
            ("products.messaging.backend.provider_imports.runs.start_provider_import_workflow", {}),
            (
                "products.messaging.backend.services.customerio_client.requests.Session.request",
                {"side_effect": _customerio_answer},
            ),
        ):
            patcher = patch(target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _import(self, api_key: str | None = "app-key") -> dict[str, Any]:
        run = runs.start_run(self.team.id, "customerio", ["transactional"], api_key, self.user.id)
        try:
            runs.run_step(self.team.id, run.id, "transactional", attempt=1)
        except ImportStepBlocked:
            pass
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run.progress["transactional"]

    def _verified_sender(self) -> Integration:
        return Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )

    def test_each_language_becomes_a_transactional_template_and_a_second_import_keeps_edits(self) -> None:
        sender = self._verified_sender()

        progress = self._import()

        templates = {t.key: t for t in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert set(templates) == {"customerio-transactional-7", "customerio-transactional-7-fr"}
        reset = templates["customerio-transactional-7"]
        email = reset.content["email"]
        assert reset.transactional_hog_flow_id is not None
        assert templates["customerio-transactional-7-fr"].transactional_hog_flow_id is not None
        assert reset.sensitive is True
        assert email["from"]["integrationId"] == sender.id
        assert email["subject"] == "Reset your password, {{variables.customer.first_name | default: 'there'}}"
        assert "{% for step in variables.steps %}" in email["html"]
        assert email["text"] == "Reset here: {{variables.reset_url}}"
        assert progress["counts"] == {"needs_review": 1, "created": 1, "empty": 1, "failed": 1}
        notes = " ".join(note for item in progress["items"] for note in item["notes"])
        assert "customerio-transactional-7-fr" in notes
        assert "reads steps and reset_url" in notes and '"customer": {"first_name": ...}' in notes

        MessageTemplate.objects.filter(id=reset.id).update(name="Edited by the team")
        progress = self._import(api_key=None)

        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == 2
        assert MessageTemplate.objects.get(id=reset.id).name == "Edited by the team"
        assert progress["counts"] == {"already_present": 2, "empty": 1, "failed": 1}

    def test_no_verified_sender_fails_the_step_and_creates_nothing(self) -> None:
        progress = self._import()

        assert progress["status"] == "failed"
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()

    @patch(PROVIDER_FLAGS_PATH, return_value=False)
    def test_transactional_email_off_hides_the_step_and_refuses_it(self, _flags: MagicMock) -> None:
        self._verified_sender()
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"

        providers = self.client.get(f"{url}providers/").json()
        response = self.client.post(url, {"provider": "customerio", "steps": ["transactional"], "api_key": "app-key"})

        customerio = next(provider for provider in providers if provider["key"] == "customerio")
        assert "transactional" not in [step["key"] for step in customerio["steps"]]
        assert "Transactional messages stay in Customer.io" in customerio["not_imported"]
        assert not any("transactional send" in step for step in customerio["next_steps"])
        assert response.status_code == 400
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()
