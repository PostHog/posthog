import os

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.models.team.team import Team
from posthog.models.web_preaggregated.team_selection import (
    DEFAULT_ENABLED_TEAM_IDS,
    DEFAULT_WEEKLY_PAGEVIEWS_THRESHOLD,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME,
    get_teams_by_weekly_pageviews_sql,
)
from posthog.models.web_preaggregated.team_selection_strategies import strategy_registry


def validate_team_ids(context: dagster.OpExecutionContext, team_ids: set[int]) -> set[int]:
    if not team_ids:
        return team_ids

    try:
        existing_teams = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
        invalid_teams = team_ids - existing_teams

        if invalid_teams:
            context.log.warning(
                f"Found {len(invalid_teams)} invalid team IDs that will be excluded: {sorted(invalid_teams)}"
            )

        context.log.info(f"Validated {len(existing_teams)} out of {len(team_ids)} team IDs")
        return existing_teams

    except Exception as e:
        context.log.warning(f"Failed to validate team IDs: {e}. Proceeding with unvalidated teams.")
        return team_ids


def get_team_ids_from_sources(context: dagster.OpExecutionContext) -> list[int]:
    all_team_ids = set(DEFAULT_ENABLED_TEAM_IDS)  # Always include defaults

    enabled_strategy_names = os.getenv(
        "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES", "project_settings,environment_variable"
    ).split(",")
    enabled_strategy_names = [s.strip().lower() for s in enabled_strategy_names]

    available_strategies = strategy_registry.get_available_strategies()
    invalid_strategies = set(enabled_strategy_names) - set(available_strategies)
    if invalid_strategies:
        context.log.warning(f"Unknown strategies will be ignored: {invalid_strategies}")

    valid_strategy_names = [s for s in enabled_strategy_names if s in available_strategies]
    context.log.info(f"Enabled strategies: {valid_strategy_names}")

    for strategy_name in valid_strategy_names:
        strategy = strategy_registry.get_strategy(strategy_name)
        if strategy:
            try:
                strategy_teams = strategy.get_teams(context)
                all_team_ids.update(strategy_teams)
            except Exception as e:
                context.log.warning(f"Strategy '{strategy_name}' failed: {e}")

    # Validate team IDs exist
    validated_team_ids = validate_team_ids(context, all_team_ids)

    team_list = sorted(validated_team_ids)
    context.log.info(f"Total validated team IDs: {len(team_list)}")
    return team_list


def store_team_selection_in_clickhouse(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    context.log.info(f"Storing {len(team_ids)} enabled team IDs in ClickHouse")

    if not team_ids:
        context.log.warning("No team IDs to store")
        return team_ids

    def insert(client: Client) -> bool:
        try:
            client.execute(
                WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL(team_ids),
                settings=settings_with_log_comment(context),
            )
            context.log.info("Successfully inserted team selection")
            return True
        except Exception as e:
            context.log.warning(f"Failed to insert team selection: {e}")
            return False

    def reload_dict(client: Client) -> bool:
        try:
            client.execute(
                f"SYSTEM RELOAD DICTIONARY {WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}",
                settings=settings_with_log_comment(context),
            )
            context.log.info("Successfully reloaded team selection dictionary")
            return True
        except Exception as e:
            context.log.warning(f"Failed to reload team selection dictionary: {e}")
            return False

    # Execute operations on all hosts
    insert_results = cluster.map_all_hosts(insert).result()
    reload_results = cluster.map_all_hosts(reload_dict).result()

    # Check if all operations succeeded
    if not all(insert_results.values()):
        raise Exception(f"Failed to insert team selection on some hosts: {insert_results}")

    if not all(reload_results.values()):
        raise Exception(f"Failed to reload dictionary on some hosts: {reload_results}")

    return team_ids


def _web_analytics_team_selection_impl(
    context: dagster.AssetExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> dagster.MaterializeResult:
    context.log.info(f"Getting team IDs from sources tables")
    team_ids = get_team_ids_from_sources(context)

    context.log.info(f"Materializing team selection for {len(team_ids)} teams")
    stored_team_ids = store_team_selection_in_clickhouse(context, team_ids, cluster)

    context.log.info(f"Successfully materialized team selection for {len(stored_team_ids)} teams")

    metadata = {
        "team_count": len(stored_team_ids),
        "team_ids": str(stored_team_ids),
    }

    return dagster.MaterializeResult(metadata=metadata)


@dagster.asset(
    name="web_analytics_team_selection",
    group_name="web_analytics",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_team_selection(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    This manages which teams have access to web analytics pre-aggregated tables.
    The selection is then stored in a ClickHouse dictionary for fast lookups.
    """
    return _web_analytics_team_selection_impl(context, cluster)


@dagster.asset(
    name="web_analytics_team_selection_v2",
    group_name="web_analytics_v2",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_team_selection_v2(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """This is the same as the team_selection on the web_analytics group but here to make the v2 graph independent"""
    return _web_analytics_team_selection_impl(context, cluster)


@dagster.asset(
    name="web_analytics_high_volume_team_candidates",
    group_name="web_analytics_v2",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_high_volume_team_candidates(
    context: dagster.AssetExecutionContext,
) -> dagster.MaterializeResult:
    """
    Materializes the list of teams qualifying for pre-aggregation based on weekly pageview volume.

    Teams qualify if they had more than 500k average weekly pageviews over the last 4 complete
    weeks, with data in all 4 weeks (ensuring constant traffic, not spikes).
    """
    try:
        threshold = int(os.getenv("WEB_ANALYTICS_WEEKLY_PAGEVIEWS_THRESHOLD", str(DEFAULT_WEEKLY_PAGEVIEWS_THRESHOLD)))
    except ValueError:
        context.log.warning(
            f"Invalid WEB_ANALYTICS_WEEKLY_PAGEVIEWS_THRESHOLD, using default {DEFAULT_WEEKLY_PAGEVIEWS_THRESHOLD}"
        )
        threshold = DEFAULT_WEEKLY_PAGEVIEWS_THRESHOLD

    sql = get_teams_by_weekly_pageviews_sql(threshold)
    context.log.info(f"Querying for teams with >{threshold:,} avg weekly pageviews over last 4 weeks")
    result = sync_execute(sql)

    team_candidates = []
    total_avg_weekly_pageviews = 0
    for row in result:
        team_id, avg_pv, min_pv, max_pv = int(row[0]), int(row[1]), int(row[2]), int(row[3])
        team_candidates.append(
            {
                "team_id": team_id,
                "avg_weekly_pageviews": avg_pv,
                "min_weekly_pageviews": min_pv,
                "max_weekly_pageviews": max_pv,
            }
        )
        total_avg_weekly_pageviews += avg_pv

    team_ids = [tc["team_id"] for tc in team_candidates]

    context.log.info(f"Found {len(team_candidates)} teams qualifying with >{threshold:,} avg weekly pageviews")
    for tc in team_candidates:
        context.log.info(
            f"  Team {tc['team_id']}: avg={tc['avg_weekly_pageviews']:,}/week, "
            f"min={tc['min_weekly_pageviews']:,}, max={tc['max_weekly_pageviews']:,}"
        )
    context.log.info(f"Total estimated weekly pageviews across all candidates: {total_avg_weekly_pageviews:,}")

    metadata = {
        "team_count": len(team_candidates),
        "team_ids": str(team_ids),
        "threshold": threshold,
        "total_avg_weekly_pageviews": total_avg_weekly_pageviews,
        "team_details": str(team_candidates),
    }

    return dagster.MaterializeResult(metadata=metadata)


web_analytics_team_candidates_job = dagster.define_asset_job(
    name="web_analytics_team_candidates_job",
    selection=["web_analytics_high_volume_team_candidates"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="0 2 * * 1",  # Weekly on Monday at 2am UTC
    job=web_analytics_team_candidates_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_team_candidates_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()
