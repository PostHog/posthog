from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest, _create_person, flush_persons_and_events

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.models.message_assets.sql import INSERT_MESSAGE_ASSET_SQL, TRUNCATE_MESSAGE_ASSETS_TABLE_SQL
from posthog.models.person.sql import TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL, TRUNCATE_PERSON_TABLE_SQL
from posthog.models.person.util import create_person_distinct_id
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
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

    def _get(self, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/messaging_recipients/", params)

    def _list(self, **params: Any) -> dict[str, Any]:
        response = self._get(**params)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _emails(self, **params: Any) -> list[str]:
        return [row["email"] for row in self._list(**params)["results"]]

    def _prefer(self, identifier: str, preferences: dict[str, str], team: Team | None = None) -> None:
        MessageRecipientPreference.objects.create(
            team=team or self.team, identifier=identifier, preferences=preferences
        )

    def _suppress(
        self, identifier: str, source: str = "BOUNCE", reason: str | None = None, team: Team | None = None
    ) -> None:
        team = team or self.team
        MessageSuppression.objects.for_team(team.id).create(
            team=team, identifier=identifier, source=source, reason=reason, suppressed=True, suppressed_at=NOW
        )

    def _person(
        self, email: str | None, distinct_id: str | None = None, name: str | None = None, team: Team | None = None
    ) -> str:
        properties = {key: value for key, value in {"email": email, "name": name}.items() if value is not None}
        person = _create_person(
            team=team or self.team, distinct_ids=[distinct_id or email or "anonymous"], properties=properties
        )
        flush_persons_and_events()
        return str(person.uuid)

    def _send(self, recipient: str, sent_at: datetime, team: Team | None = None) -> None:
        sync_execute(
            INSERT_MESSAGE_ASSET_SQL,
            {
                "team_id": (team or self.team).id,
                "function_kind": "hog_flow",
                "function_id": "flow",
                "parent_run_id": "",
                "invocation_id": f"run-{recipient}-{sent_at.isoformat()}",
                "action_id": "email-step",
                "kind": "email",
                "distinct_id": recipient,
                "person_id": "",
                "recipient": recipient,
                "subject": "Hello",
                "html": "",
                "status": "sent",
                "sent_at": sent_at,
                "version": 1,
                "is_deleted": 0,
            },
        )

    def _deny_hog_flow_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="none")

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
        with time_machine.travel(NOW - timedelta(days=1), tick=False):
            self._prefer(
                "Jamie@Example.com", {"$all": "OPTED_IN", newsletter: "OPTED_OUT", product_updates: "OPTED_IN"}
            )
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
        assert self._emails(filter=["subscribed:newsletter"]) == []
        assert self._emails(filter=["unsubscribed:newsletter"]) == ["jamie@example.com"]
        assert self._emails(filter=["unsubscribed:all-marketing"]) == ["jamie@example.com"]

    def _seed_facet_audience(self) -> None:
        newsletter = self._topic("newsletter")
        self._prefer("ann@example.com", {newsletter: "OPTED_OUT"})
        self._person("ann@example.com")
        self._prefer("ben@example.com", {newsletter: "OPTED_IN", "$all": "OPTED_OUT"})
        self._suppress("cat@example.com", source="BOUNCE")
        self._person("cat@example.com")
        self._suppress("dan@example.com", source="MANUAL")
        self._prefer("dan@example.com", {newsletter: "OPTED_IN", "$all": "OPTED_IN"})
        self._person("eve@example.com")

    @parameterized.expand(
        [
            ("subscribed", {"filter": ["subscribed:newsletter"]}, ["ben", "dan"]),
            (
                "subscribed_reports_the_topic_status_even_under_an_all_marketing_opt_out",
                {"filter": ["subscribed:newsletter", "unsubscribed:all-marketing"]},
                ["ben"],
            ),
            ("negated_topic", {"filter": ["-subscribed:newsletter"]}, ["ann", "cat", "eve"]),
            ("subscribed_to_all_marketing", {"filter": ["subscribed:all-marketing"]}, ["dan"]),
            ("unsubscribed", {"filter": ["unsubscribed:newsletter"]}, ["ann"]),
            ("no_preference", {"filter": ["no-preference:newsletter"]}, ["cat", "eve"]),
            ("unsubscribed_from_all_marketing", {"filter": ["unsubscribed:all-marketing"]}, ["ben"]),
            ("no_preference_on_all_marketing", {"filter": ["no-preference:all-marketing"]}, ["ann", "cat", "eve"]),
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
            ("unknown_facet", {"filter": "colour:red"}),
            ("unknown_topic", {"filter": "subscribed:nope"}),
            ("unknown_suppression_source", {"filter": "suppressed:SPAM"}),
            ("unknown_person_value", {"filter": "person:maybe"}),
            ("missing_value", {"filter": "person:"}),
            ("not_a_facet_filter", {"filter": "newsletter"}),
            ("unknown_facet_next_to_an_email", {"filter": "colour:red", "email": "jamie@example.com"}),
            ("unknown_topic_next_to_an_email", {"filter": "subscribed:nope", "email": "jamie@example.com"}),
        ]
    )
    def test_rejects_an_unknown_filter(self, _name: str, params: dict[str, str]) -> None:
        self._topic("newsletter")
        self._prefer("jamie@example.com", {})

        response = self._get(**params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "filter"

    def test_pages_by_cursor_return_every_recipient_exactly_once(self) -> None:
        self._prefer("a@example.com", {})
        self._suppress("b@example.com")
        self._person("c@example.com")
        self._prefer("d@example.com", {})
        self._person("e@example.com")

        pages: list[list[str]] = []
        cursor: str | None = None
        while len(pages) < 4:
            page = self._list(limit=2, **({"cursor": cursor} if cursor else {}))
            pages.append([row["email"] for row in page["results"]])
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert pages == [
            ["a@example.com", "b@example.com"],
            ["c@example.com", "d@example.com"],
            ["e@example.com"],
        ]

    @parameterized.expand(
        [
            ("ending_in_whitespace_the_send_path_keeps", "a@example.com\u0085", "\u0085"),
            ("longer_than_any_stored_identifier", f"a{'x' * 600}@example.com", "axxxxxxxxxx"),
        ]
    )
    def test_the_next_cursor_email_lookup_and_search_accept_every_listed_address(
        self, _name: str, address: str, search: str
    ) -> None:
        self._person(address, distinct_id="first")
        self._person("b@example.com")

        first = self._list(limit=1)
        second = self._list(limit=1, cursor=first["next_cursor"])

        assert [row["email"] for row in first["results"] + second["results"]] == [address, "b@example.com"]
        assert self._emails(email=address) == [address]
        assert self._emails(search=search) == [address]

    def test_pages_a_filtered_list_by_cursor(self) -> None:
        self._seed_facet_audience()

        first = self._list(limit=2, filter=["person:linked"], search="@")
        second = self._list(limit=2, filter=["person:linked"], search="@", cursor=first["next_cursor"])

        assert [row["email"] for row in first["results"] + second["results"]] == [
            "ann@example.com",
            "cat@example.com",
            "eve@example.com",
        ]
        assert second["next_cursor"] is None

    @parameterized.expand(
        [
            ("non_ascii_casing", "Jürgen.MÜLLER@example.com", "jürgen.müller@example.com", "MÜLLER"),
            ("surrounding_whitespace", "\tTab@Example.com \n", "tab@example.com", "TAB@"),
            (
                "unicode_whitespace_the_send_path_trims",
                "\ufeff\u3000Nb\u00a0Inner@Example.com\u00a0",
                "nb\u00a0inner@example.com",
                "B\u00a0INNER",
            ),
        ]
    )
    def test_folds_an_address_the_same_way_in_list_search_and_lookup(
        self, _name: str, stored: str, folded: str, search: str
    ) -> None:
        self._prefer(stored, {})
        self._suppress(stored)
        self._person(stored, distinct_id="holder")

        assert self._emails() == [folded]
        assert self._emails(search=search) == [folded]
        assert self._emails(email=stored.upper()) == [folded]

    def test_ignores_removed_preferences_and_suppressions_that_do_not_block_sends(self) -> None:
        MessageRecipientPreference.objects.create(
            team=self.team, identifier="kim@example.com", preferences={"$all": "OPTED_OUT"}, deleted=True
        )
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team, identifier="kim@example.com", source="BOUNCE", suppressed=False, transient_bounce_count=1
        )
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team,
            identifier="KIM@example.com",
            source="MANUAL",
            suppressed=True,
            suppressed_at=NOW,
            deleted=True,
        )
        self._person("kim@example.com")

        [recipient] = self._list()["results"]

        assert (recipient["all_marketing"], recipient["suppression"], recipient["preferences_updated_at"]) == (
            "NO_PREFERENCE",
            None,
            None,
        )

    def test_counts_every_person_holding_an_address_and_previews_three(self) -> None:
        holders = [self._person("shared@example.com", distinct_id=f"holder-{index}") for index in range(3)]
        two_ids = _create_person(
            team=self.team, distinct_ids=["holder-b", "holder-a"], properties={"email": "Shared@Example.com"}
        )
        flush_persons_and_events()

        [recipient] = self._list()["results"]

        assert recipient["person_count"] == 4
        assert [person["uuid"] for person in recipient["persons"]] == sorted([*holders, str(two_ids.uuid)])[:3]

    def test_previews_the_distinct_ids_of_every_person_on_a_page(self) -> None:
        distinct_ids = [f"holder-{address}-{index}" for address in range(40) for index in range(3)]
        distinct_id_by_person = {}
        for distinct_id in distinct_ids:
            person = _create_person(
                team=self.team, distinct_ids=[distinct_id], properties={"email": f"{distinct_id[:-2]}@example.com"}
            )
            distinct_id_by_person[str(person.uuid)] = distinct_id
        flush_persons_and_events()

        results = self._list()["results"]

        assert {person["uuid"]: person["distinct_id"] for row in results for person in row["persons"]} == (
            distinct_id_by_person
        )

    @parameterized.expand(
        [
            ("moved_to_another_person", False),
            ("deleted", True),
        ]
    )
    def test_previews_only_a_distinct_id_the_person_still_holds(self, _name: str, is_deleted: bool) -> None:
        holder = _create_person(
            team=self.team, distinct_ids=["a-gone", "z-kept"], properties={"email": "holder@example.com"}
        )
        other = _create_person(team=self.team, distinct_ids=["other"], properties={})
        flush_persons_and_events()
        create_person_distinct_id(
            self.team.id, "a-gone", str(holder.uuid if is_deleted else other.uuid), version=1, is_deleted=is_deleted
        )

        [recipient] = self._list()["results"]

        assert [person["distinct_id"] for person in recipient["persons"]] == ["z-kept"]

    def test_never_lists_an_identifier_that_is_only_whitespace(self) -> None:
        self._prefer(" \t", {"$all": "OPTED_OUT"})
        self._suppress("  ")
        self._prefer("a@example.com", {})

        assert self._emails() == ["a@example.com"]

    def test_ignores_a_preference_row_that_is_not_a_map(self) -> None:
        self._prefer("broken@example.com", ["OPTED_OUT"])  # type: ignore[arg-type]

        assert self._list()["results"][0]["topics"] == {}

    def test_email_returns_exactly_that_recipient(self) -> None:
        self._prefer("Jamie@Example.com", {})
        self._prefer("jamie.other@example.com", {})

        assert self._emails(email=" JAMIE@example.com") == ["jamie@example.com"]

    @parameterized.expand(
        [
            ("unknown_address", {"email": "nobody@example.com"}),
            ("address_outside_the_filter", {"email": "jamie@example.com", "filter": "suppressed:BOUNCE"}),
        ]
    )
    def test_email_without_a_matching_recipient_is_not_found(self, _name: str, params: dict[str, str]) -> None:
        self._prefer("jamie@example.com", {})

        assert self._get(**params).status_code == status.HTTP_404_NOT_FOUND

    @time_machine.travel(NOW, tick=False)
    def test_never_lists_another_teams_recipients(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._prefer("theirs@example.com", {}, team=other_team)
        self._suppress("theirs@example.com", team=other_team)
        self._person("theirs@example.com", team=other_team)
        self._send("ours@example.com", NOW - timedelta(days=1), team=other_team)
        self._prefer("ours@example.com", {})

        assert [(row["email"], row["last_sent_at"]) for row in self._list()["results"]] == [("ours@example.com", None)]

    @parameterized.expand(
        [
            ("list_without_a_grant", "", [], status.HTTP_403_FORBIDDEN),
            ("coverage_without_a_grant", "coverage/", [], status.HTTP_403_FORBIDDEN),
            ("list_with_only_a_workflow_grant", "", ["flow-granted"], status.HTTP_403_FORBIDDEN),
            ("coverage_with_only_a_workflow_grant", "coverage/", ["flow-granted"], status.HTTP_403_FORBIDDEN),
            ("list_as_a_workflows_viewer", "", [None], status.HTTP_200_OK),
            ("coverage_as_a_workflows_viewer", "coverage/", [None], status.HTTP_200_OK),
        ]
    )
    def test_needs_hog_flow_viewer_access(
        self, _name: str, path: str, viewer_grants: list[str | None], expected_status: int
    ) -> None:
        self._deny_hog_flow_access()
        for resource_id in viewer_grants:
            AccessControl.objects.create(
                team=self.team,
                resource="hog_flow",
                resource_id=resource_id,
                access_level="viewer",
                organization_member=self.organization_membership,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/messaging_recipients/{path}")

        assert response.status_code == expected_status

    @parameterized.expand(
        [
            ("list_with_both_scopes", "", ["hog_flow:read", "person:read"], status.HTTP_200_OK),
            ("list_without_person_read", "", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
            ("list_without_hog_flow_read", "", ["person:read"], status.HTTP_403_FORBIDDEN),
            ("coverage_without_person_read", "coverage/", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_personal_api_keys_need_workflow_and_person_read(
        self, _name: str, path: str, scopes: list[str], expected_status: int
    ) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="Test", user=self.user, secure_value=hash_key_value(key), scopes=scopes)
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_recipients/{path}", HTTP_AUTHORIZATION=f"Bearer {key}"
        )

        assert response.status_code == expected_status

    @time_machine.travel(NOW, tick=False)
    def test_last_sent_at_comes_from_sends_in_the_last_30_days(self) -> None:
        recent = NOW - timedelta(days=2)
        self._prefer("recent@example.com", {})
        self._prefer("stale@example.com", {})
        self._send("Recent@Example.com", recent - timedelta(days=1))
        self._send("\u2028Recent@Example.com\u00a0", recent)
        self._send("stale@example.com", recent - timedelta(days=40))

        last_sent = {row["email"]: row["last_sent_at"] for row in self._list()["results"]}

        assert last_sent == {
            "recent@example.com": recent.isoformat().replace("+00:00", "Z"),
            "stale@example.com": None,
        }

    def test_coverage_counts_persons_without_an_email(self) -> None:
        self._person("reachable@example.com")
        self._person(None, distinct_id="anonymous-1")
        self._person(None, distinct_id="anonymous-2", name="No Email")
        self._person("", distinct_id="blank-email")
        self._person("   ", distinct_id="whitespace-email")
        self._person("\u00a0", distinct_id="non-breaking-space-email")
        self._person(None, distinct_id="other-team-anonymous", team=Team.objects.create(organization=self.organization))

        response = self.client.get(f"/api/projects/{self.team.id}/messaging_recipients/coverage/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"persons_without_email": 5}
        assert self._emails() == ["reachable@example.com"]
