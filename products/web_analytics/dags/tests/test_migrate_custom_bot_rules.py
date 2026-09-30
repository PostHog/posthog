import pytest

import dagster

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.web_analytics.dags.migrate_custom_bot_rules import web_analytics_migrate_custom_bot_rules_job

FLAT_RULE = {"id": "r1", "name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}


def _run(config: dict | None) -> dagster.ExecuteInProcessResult:
    run_config = {"ops": {"migrate_custom_bot_rules_op": {"config": config}}} if config else None
    return web_analytics_migrate_custom_bot_rules_job.execute_in_process(run_config=run_config, raise_on_error=False)


@pytest.mark.django_db
@pytest.mark.parametrize("config,expect_migrated", [(None, False), ({"execute": True}, True)])
def test_job_migrates_only_when_execute_is_set(config, expect_migrated):
    org = Organization.objects.create(name="test-org-bot-rules")
    team = Team.objects.create(
        organization=org, name="test-team-bot-rules", modifiers={"customBotDefinitions": [FLAT_RULE]}
    )

    result = _run(config)
    assert result.success

    team.refresh_from_db()
    migrated = "items" in team.modifiers["customBotDefinitions"][0]
    assert migrated is expect_migrated
