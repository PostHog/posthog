from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest, _create_person, flush_persons_and_events

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.message_assets.sql import TRUNCATE_MESSAGE_ASSETS_TABLE_SQL
from posthog.models.person.sql import TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL, TRUNCATE_PERSON_TABLE_SQL

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_suppression import MessageSuppression

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


class TestMessageRecipients(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Sequences reset between these non-atomic tests, so every test reuses the same team id and
        # would otherwise read the previous test's ClickHouse persons and sends.
        for statement in (
            TRUNCATE_PERSON_TABLE_SQL,
            TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
            TRUNCATE_MESSAGE_ASSETS_TABLE_SQL,
        ):
            sync_execute(statement)

    def _list(self, **params: Any) -> dict[str, Any]:
        response = self._get(**params)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _get(self, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/messaging_recipients/", params)

    def _emails(self, **params: Any) -> list[str]:
        return [row["email"] for row in self._list(**params)["results"]]

    def _prefer(self, identifier: str, preferences: dict[str, str]) -> None:
        MessageRecipientPreference.objects.create(team=self.team, identifier=identifier, preferences=preferences)

    def _suppress(self, identifier: str, source: str = "BOUNCE", reason: str | None = None) -> None:
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team, identifier=identifier, source=source, reason=reason, suppressed=True, suppressed_at=NOW
        )

    def _person(self, email: str, distinct_id: str | None = None, name: str | None = None) -> str:
        properties = {"email": email} if name is None else {"email": email, "name": name}
        person = _create_person(team=self.team, distinct_ids=[distinct_id or email], properties=properties)
        flush_persons_and_events()
        return str(person.uuid)

    def _topic(self, key: str) -> str:
        return str(MessageCategory.objects.create(team=self.team, key=key, name=key.title()).id)

    def test_lists_every_known_address_once_ordered_by_address(self) -> None:
        self._prefer("carol@example.com", {"$all": "OPTED_OUT"})
        self._suppress("bob@example.com")
        self._person("alice@example.com")
        self._person("carol@example.com")

        assert self._emails() == ["alice@example.com", "bob@example.com", "carol@example.com"]

    @time_machine.travel(NOW, tick=False)
    def test_folds_casings_of_one_address_into_one_row_where_unsubscribed_wins(self) -> None:
        newsletter = self._topic("newsletter")
        product_updates = self._topic("product-updates")
        self._prefer("Jamie@Example.com", {"$all": "OPTED_IN", newsletter: "OPTED_OUT", product_updates: "OPTED_IN"})
        self._prefer("jamie@example.com", {"$all": "OPTED_OUT", newsletter: "OPTED_IN", "$email_tracking": "OPTED_OUT"})
        self._suppress("jamie@example.com", source="COMPLAINT", reason="Marked as spam")
        person_uuid = self._person("JAMIE@example.com ", distinct_id="jamie-1", name="Jamie")

        assert self._list()["results"] == [
            {
                "email": "jamie@example.com",
                "all_marketing": "OPTED_OUT",
                "topics": {"newsletter": "OPTED_OUT", "product-updates": "OPTED_IN"},
                "suppression": {
                    "source": "COMPLAINT",
                    "reason": "Marked as spam",
                    "suppressed_at": "2026-09-15T10:00:00Z",
                },
                "persons": [{"uuid": person_uuid, "distinct_id": "jamie-1", "name": "Jamie"}],
                "person_count": 1,
                "last_sent_at": None,
                "preferences_updated_at": "2026-09-15T10:00:00Z",
            }
        ]

    def _seed_facet_audience(self) -> None:
        newsletter = self._topic("newsletter")
        self._prefer("ann@example.com", {newsletter: "OPTED_OUT"})
        self._person("ann@example.com")
        self._prefer("ben@example.com", {newsletter: "OPTED_IN", "$all": "OPTED_OUT"})
        self._suppress("cat@example.com", source="BOUNCE")
        self._person("cat@example.com")
        self._suppress("dan@example.com", source="MANUAL")
        self._prefer("dan@example.com", {newsletter: "OPTED_IN"})
        self._person("eve@example.com")

    @parameterized.expand(
        [
            ("subscribed", {"filter": ["subscribed:newsletter"]}, ["ben", "dan"]),
            ("unsubscribed", {"filter": ["unsubscribed:newsletter"]}, ["ann"]),
            ("no_preference", {"filter": ["no-preference:newsletter"]}, ["cat", "eve"]),
            ("unsubscribed_from_all_marketing", {"filter": ["unsubscribed:all-marketing"]}, ["ben"]),
            (
                "no_preference_on_all_marketing",
                {"filter": ["no-preference:all-marketing"]},
                ["ann", "cat", "dan", "eve"],
            ),
            ("suppressed", {"filter": ["suppressed:BOUNCE"]}, ["cat"]),
            ("values_on_one_facet_are_or", {"filter": ["suppressed:BOUNCE", "suppressed:MANUAL"]}, ["cat", "dan"]),
            ("negated", {"filter": ["-suppressed:BOUNCE"]}, ["ann", "ben", "dan", "eve"]),
            ("person_linked", {"filter": ["person:linked"]}, ["ann", "cat", "eve"]),
            ("person_none", {"filter": ["person:none"]}, ["ben", "dan"]),
            ("preference_recorded", {"filter": ["preference:recorded"]}, ["ann", "ben", "dan"]),
            ("preference_none", {"filter": ["preference:none"]}, ["cat", "eve"]),
            ("facets_are_and", {"filter": ["preference:recorded", "person:linked"]}, ["ann"]),
            ("negation_and_across_facets", {"filter": ["subscribed:newsletter", "-suppressed:MANUAL"]}, ["ben"]),
            ("search_is_a_case_insensitive_substring", {"search": "AN"}, ["ann", "dan"]),
            ("search_and_filter", {"search": "an", "filter": ["person:linked"]}, ["ann"]),
        ]
    )
    def test_filters_recipients(self, _name: str, params: dict[str, Any], expected: list[str]) -> None:
        self._seed_facet_audience()

        assert self._emails(**params) == [f"{name}@example.com" for name in expected]

    @parameterized.expand(
        [
            ("unknown_facet", "colour:red"),
            ("unknown_topic", "subscribed:nope"),
            ("unknown_suppression_source", "suppressed:SPAM"),
            ("unknown_person_value", "person:maybe"),
            ("missing_value", "person:"),
            ("not_a_facet_filter", "newsletter"),
        ]
    )
    def test_rejects_an_unknown_filter(self, _name: str, raw_filter: str) -> None:
        self._topic("newsletter")

        response = self._get(filter=raw_filter)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "filter"
