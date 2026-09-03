from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status


class TestCustomBotRulesAPI(ClickhouseTestMixin, APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_bot_rules/{suffix}"

    def test_create_list_and_delete_round_trip(self) -> None:
        create = self.client.post(
            self._url(),
            {"name": "Office scraper", "key": "$ip", "matcher": "cidr", "pattern": "192.0.2.0/24"},
        )
        assert create.status_code == status.HTTP_201_CREATED, create.json()
        rule_id = create.json()["id"]

        self.team.refresh_from_db()
        stored = self.team.modifiers["customBotDefinitions"]
        assert [rule["name"] for rule in stored] == ["Office scraper"]

        listed = self.client.get(self._url())
        assert [rule["id"] for rule in listed.json()] == [rule_id]

        deleted = self.client.delete(self._url(f"{rule_id}/"))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        self.team.refresh_from_db()
        assert self.team.modifiers["customBotDefinitions"] == []

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
