"""Operator job to rewrite flat custom bot rules into the multi-condition shape.

The multi-condition bot rules change dropped support for the original flat rule shape
({key, matcher, pattern} on the rule itself), so teams with flat rules stored on
team.modifiers have those rules silently skipped at query time until they are rewritten.

Run manually from the Dagster UI. With no run config it only lists the affected teams
(dry run); the rewrite requires explicitly setting `execute: true`. Each team is one
atomic UPDATE that touches only the customBotDefinitions key of team.modifiers, so other
modifier keys and their query cache keys are unaffected, and re-running is a no-op.
"""

import dagster

from posthog.dags.common import JobOwners

from products.web_analytics.backend.custom_bot_rules_migration import find_teams_with_flat_rules, migrate_team


class MigrateCustomBotRulesConfig(dagster.Config):
    execute: bool = False


@dagster.op
def migrate_custom_bot_rules_op(context: dagster.OpExecutionContext, config: MigrateCustomBotRulesConfig) -> None:
    teams = find_teams_with_flat_rules()
    if not teams:
        context.log.info("No teams with flat custom bot rules found")
        return

    total_rules = sum(team.flat_rules for team in teams)
    context.log.info(f"{len(teams)} team(s) with {total_rules} flat rule(s)")
    for team in teams:
        context.log.info(f"team {team.team_id}: {team.flat_rules} flat rule(s)")

    if not config.execute:
        context.log.info("Dry run: no `execute: true` in run config, nothing changed")
        return

    migrated = sum(1 for team in teams if migrate_team(team.team_id))
    context.log.info(f"Migrated {migrated}/{len(teams)} team(s)")


@dagster.job(
    name="web_analytics_migrate_custom_bot_rules",
    description=(
        "Rewrite flat custom bot rules stored on team.modifiers into the multi-condition "
        "shape. Without run config this is a dry run that lists affected teams; set "
        "`execute: true` to apply the rewrite."
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_migrate_custom_bot_rules_job() -> None:
    migrate_custom_bot_rules_op()
