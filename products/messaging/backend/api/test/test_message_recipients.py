from typing import Any

from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest, _create_person, flush_persons_and_events

from rest_framework import status

from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_suppression import MessageSuppression


class TestMessageRecipients(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    def _list(self, **params: Any) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/messaging_recipients/", params)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _emails(self, **params: Any) -> list[str]:
        return [row["email"] for row in self._list(**params)["results"]]

    def _prefer(self, identifier: str, preferences: dict[str, str]) -> None:
        MessageRecipientPreference.objects.create(team=self.team, identifier=identifier, preferences=preferences)

    def _suppress(self, identifier: str, source: str = "BOUNCE") -> None:
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team, identifier=identifier, source=source, suppressed=True
        )

    def _person(self, email: str, distinct_id: str | None = None) -> None:
        _create_person(team=self.team, distinct_ids=[distinct_id or email], properties={"email": email})
        flush_persons_and_events()

    def test_lists_every_known_address_once_ordered_by_address(self) -> None:
        self._prefer("carol@example.com", {"$all": "OPTED_OUT"})
        self._suppress("bob@example.com")
        self._person("alice@example.com")
        self._person("carol@example.com")

        assert self._emails() == ["alice@example.com", "bob@example.com", "carol@example.com"]
