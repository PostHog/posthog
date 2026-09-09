from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership


class TestCustomBotRulesAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A rule is stored on the admin-only `modifiers` setting, so mutating it needs project admin.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_bot_rules/{suffix}"

    def test_non_admin_cannot_mutate_but_can_list(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        create = self.client.post(
            self._url(),
            {"name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"},
        )
        assert create.status_code == status.HTTP_403_FORBIDDEN, create.json()
        assert self.client.delete(self._url("any-id/")).status_code == status.HTTP_403_FORBIDDEN
        # Reading the rules is not gated.
        assert self.client.get(self._url()).status_code == status.HTTP_200_OK

    def test_create_list_and_delete_round_trip(self) -> None:
        # The flat single-condition body is the pre-combiner shape; the endpoint keeps accepting it
        # because the generated MCP tool sends it until it redeploys.
        create = self.client.post(
            self._url(),
            {"name": "Office scraper", "key": "$ip", "matcher": "cidr", "pattern": "192.0.2.0/24"},
        )
        assert create.status_code == status.HTTP_201_CREATED, create.json()
        rule_id = create.json()["id"]
        assert [item["pattern"] for item in create.json()["items"]] == ["192.0.2.0/24"]

        self.team.refresh_from_db()
        stored = self.team.modifiers["customBotDefinitions"]
        assert [rule["name"] for rule in stored] == ["Office scraper"]

        listed = self.client.get(self._url())
        assert [rule["id"] for rule in listed.json()] == [rule_id]

        deleted = self.client.delete(self._url(f"{rule_id}/"))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        self.team.refresh_from_db()
        assert self.team.modifiers["customBotDefinitions"] == []

    def test_create_a_multi_condition_rule(self) -> None:
        create = self.client.post(
            self._url(),
            {
                "name": "Headless 800x600",
                "combiner": "AND",
                "items": [
                    {"key": "$screen_width", "matcher": "exact", "pattern": "800"},
                    {"key": "$screen_height", "matcher": "exact", "pattern": "600"},
                ],
            },
        )
        assert create.status_code == status.HTTP_201_CREATED, create.json()
        body = create.json()
        assert body["combiner"] == "AND"
        assert [(item["key"], item["matcher"], item["pattern"]) for item in body["items"]] == [
            ("$screen_width", "exact", "800"),
            ("$screen_height", "exact", "600"),
        ]

        self.team.refresh_from_db()
        assert self.team.modifiers["customBotDefinitions"] == [body]

    def test_list_upcasts_rules_stored_in_the_flat_shape(self) -> None:
        # Rules saved before conditions existed keep the flat shape in team.modifiers; the list
        # endpoint has to report one shape or every consumer needs both parsers.
        self.team.modifiers = {
            "customBotDefinitions": [
                {"id": "1", "name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}
            ]
        }
        self.team.save()

        listed = self.client.get(self._url())
        assert [item["pattern"] for rule in listed.json() for item in rule["items"]] == ["AcmeBot"]

    def test_create_preserves_other_modifiers(self) -> None:
        self.team.modifiers = {"bounceRateDurationSeconds": 42}
        self.team.save()

        create = self.client.post(
            self._url(),
            {"name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"},
        )
        assert create.status_code == status.HTTP_201_CREATED, create.json()

        self.team.refresh_from_db()
        assert self.team.modifiers["bounceRateDurationSeconds"] == 42
        assert len(self.team.modifiers["customBotDefinitions"]) == 1

    @parameterized.expand(
        [
            ("unknown property", {"key": "$nope", "matcher": "contains", "pattern": "AcmeBot"}),
            ("unknown matcher", {"key": "$raw_user_agent", "matcher": "startswith", "pattern": "AcmeBot"}),
            ("cidr on a non-ip property", {"key": "$raw_user_agent", "matcher": "cidr", "pattern": "192.0.2.0/24"}),
            ("regex clickhouse cannot run", {"key": "$raw_user_agent", "matcher": "regex", "pattern": "(?=lookahead)"}),
            ("blank category", {"key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot", "category": ""}),
            (
                # The id-keyed editor collapses conditions that share an id, and its next save
                # would persist the collapsed rule.
                "duplicate condition ids",
                {
                    "combiner": "AND",
                    "items": [
                        {"id": "a", "key": "$screen_width", "matcher": "exact", "pattern": "800"},
                        {"id": "a", "key": "$screen_height", "matcher": "exact", "pattern": "600"},
                    ],
                },
            ),
        ]
    )
    def test_rejects_unusable_rules(self, _name: str, body: dict) -> None:
        response = self.client.post(self._url(), {"name": "x", **body})
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        self.team.refresh_from_db()
        assert (self.team.modifiers or {}).get("customBotDefinitions", []) == []

    def test_delete_unknown_id_is_not_found(self) -> None:
        response = self.client.delete(self._url("does-not-exist/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
