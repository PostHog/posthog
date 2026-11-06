from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.web_analytics.backend.custom_bot_rules_migration import (
    FlatRuleTeam,
    find_teams_with_flat_rules,
    migrate_team,
)
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import parse_rules

FLAT_RULE = {"id": "r1", "name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}
FLAT_RULE_WITH_CATEGORY = {
    "id": "r2",
    "name": "Office",
    "key": "$ip",
    "matcher": "cidr",
    "pattern": "192.0.2.0/24",
    "category": "monitoring",
}
NEW_SHAPE_RULE = {
    "id": "r3",
    "name": "Headless",
    "combiner": "AND",
    "items": [{"id": "r3-w", "key": "$screen_width", "matcher": "exact", "pattern": "800"}],
}


class TestMigrateCustomBotRules(BaseTest):
    def _set_rules(self, rules: list) -> None:
        self.team.modifiers = {"customBotDefinitions": rules, "bounceRateDurationSeconds": 42}
        self.team.save(update_fields=["modifiers"])

    def test_rewrites_flat_rules_and_leaves_everything_else_alone(self):
        # The rewrite must produce exactly what the current reader parses, touch only the
        # customBotDefinitions key, and pass new-shape and garbage entries through unchanged —
        # a clobbered sibling modifier or a mangled entry would silently change query behavior.
        self._set_rules([FLAT_RULE, FLAT_RULE_WITH_CATEGORY, NEW_SHAPE_RULE, "garbage"])

        assert find_teams_with_flat_rules() == [FlatRuleTeam(team_id=self.team.pk, flat_rules=2)]
        assert migrate_team(self.team.pk)

        self.team.refresh_from_db()
        assert self.team.modifiers["bounceRateDurationSeconds"] == 42
        stored = self.team.modifiers["customBotDefinitions"]
        assert stored[2] == NEW_SHAPE_RULE
        assert stored[3] == "garbage"
        assert stored[0] == {
            "id": "r1",
            "name": "Acme",
            "combiner": "AND",
            "items": [{"id": "r1-condition", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}],
        }
        assert stored[1]["category"] == "monitoring"

        parsed = parse_rules(stored)
        assert [rule.name for rule in parsed] == ["Acme", "Office", "Headless"]

    def test_is_idempotent(self):
        self._set_rules([FLAT_RULE])
        assert migrate_team(self.team.pk)
        self.team.refresh_from_db()
        first_pass = self.team.modifiers["customBotDefinitions"]

        # A converted team must not qualify again, and re-running must not change the data.
        assert find_teams_with_flat_rules() == []
        assert not migrate_team(self.team.pk)
        self.team.refresh_from_db()
        assert self.team.modifiers["customBotDefinitions"] == first_pass

    def test_ignores_teams_without_flat_rules(self):
        self._set_rules([NEW_SHAPE_RULE])

        assert find_teams_with_flat_rules() == []
        assert not migrate_team(self.team.pk)

    def test_non_array_value_does_not_abort_the_scan(self):
        # jsonb_array_elements raises on a non-array, and without the CASE guard one such row
        # would abort the fleet-wide scan and block every other team's migration.
        self.team.modifiers = {"customBotDefinitions": {"not": "an array"}}
        self.team.save(update_fields=["modifiers"])
        other = Team.objects.create(
            organization=self.organization, name="flat", modifiers={"customBotDefinitions": [FLAT_RULE]}
        )

        assert find_teams_with_flat_rules() == [FlatRuleTeam(team_id=other.pk, flat_rules=1)]
        assert not migrate_team(self.team.pk)
