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
            {"name": "Acme", "items": [{"key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}]},
        )
        assert create.status_code == status.HTTP_403_FORBIDDEN, create.json()
        assert self.client.delete(self._url("any-id/")).status_code == status.HTTP_403_FORBIDDEN
        # Reading the rules is not gated.
        assert self.client.get(self._url()).status_code == status.HTTP_200_OK

    def test_create_list_and_delete_round_trip(self) -> None:
        create = self.client.post(
            self._url(),
            {"name": "Office scraper", "items": [{"key": "$ip", "matcher": "cidr", "pattern": "192.0.2.0/24"}]},
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

    @parameterized.expand(
        [
            ("unknown property", {"items": [{"key": "$nope", "matcher": "contains", "pattern": "AcmeBot"}]}),
            ("unknown matcher", {"items": [{"key": "$raw_user_agent", "matcher": "startswith", "pattern": "AcmeBot"}]}),
            (
                "cidr on a non-ip property",
                {"items": [{"key": "$raw_user_agent", "matcher": "cidr", "pattern": "192.0.2.0/24"}]},
            ),
            (
                "regex clickhouse cannot run",
                {"items": [{"key": "$raw_user_agent", "matcher": "regex", "pattern": "(?=lookahead)"}]},
            ),
            (
                "blank category",
                {"items": [{"key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}], "category": ""},
            ),
            (
                # A shared id collapses entries in the id-keyed editor.
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

    def test_create_rejects_a_rule_set_over_the_aggregate_condition_budget(self) -> None:
        # The per-rule serializer caps cannot see the stored rules, so the budget check must.
        self.team.modifiers = {
            "customBotDefinitions": [
                {
                    "id": str(i),
                    "name": f"Bot {i}",
                    "combiner": "AND",
                    "items": [
                        {"id": f"{i}-{j}", "key": "$raw_user_agent", "matcher": "contains", "pattern": f"Bot{i}-{j}"}
                        for j in range(10)
                    ],
                }
                for i in range(10)
            ]
        }
        self.team.save()

        create = self.client.post(
            self._url(),
            {"name": "One too many", "items": [{"key": "$raw_user_agent", "matcher": "contains", "pattern": "x"}]},
        )
        assert create.status_code == status.HTTP_400_BAD_REQUEST, create.json()
        assert "across all rules" in str(create.json())

    def test_delete_unknown_id_is_not_found(self) -> None:
        response = self.client.delete(self._url("does-not-exist/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
