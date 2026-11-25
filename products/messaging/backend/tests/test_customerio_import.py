from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.provider_imports import runs


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
