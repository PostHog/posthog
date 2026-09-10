import pytest

from dagster import build_op_context

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.web_analytics.dags.migrate_custom_bot_rules import (
    MigrateCustomBotRulesConfig,
    migrate_custom_bot_rules_op,
)

FLAT_RULE = {"id": "r1", "name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}


@pytest.mark.django_db
@pytest.mark.parametrize("execute,expect_migrated", [(False, False), (True, True)])
def test_op_migrates_only_when_execute_is_set(execute, expect_migrated):
    org = Organization.objects.create(name="test-org-bot-rules")
    team = Team.objects.create(
        organization=org, name="test-team-bot-rules", modifiers={"customBotDefinitions": [FLAT_RULE]}
    )

    migrate_custom_bot_rules_op(build_op_context(), MigrateCustomBotRulesConfig(execute=execute))

    team.refresh_from_db()
    migrated = "items" in team.modifiers["customBotDefinitions"][0]
    assert migrated is expect_migrated
