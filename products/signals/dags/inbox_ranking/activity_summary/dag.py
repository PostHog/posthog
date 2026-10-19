"""Inputs and a cost projection for per-person activity summaries, with no LLM call.

Two assets on the shared daily partition, each writing Parquet under the dataset prefix:

    activity_summary_inputs/v1/dt=D/           one filtered, rendered input per (project, member)
    activity_summary_cost_projection/v1/dt=D/  eligible pairs, token percentiles and monthly volume

Both read the dogfood project's events over the 28 days that end with D. The inputs asset covers only
members of the dogfood project's organization with an `@posthog.com` email, in that organization's
own projects, so no customer project's intents get in. The projection covers every pair in the
events and writes counts only.
"""

import datetime
from collections import defaultdict
from typing import Any

import dagster
import pyarrow as pa

from posthog import settings
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries
from posthog.dags.common import dagster_tags
from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User

from products.signals.dags.inbox_ranking.activity_summary import queries
from products.signals.dags.inbox_ranking.activity_summary.render import (
    RENDER_VERSION,
    WINDOW_DAYS,
    AiPrompt,
    McpCall,
    McpSession,
    PairActivity,
    ProjectionPrices,
    build_input,
    calibration_ratio,
    estimated_input_chars,
    job_intents,
    projection_rows,
    sampling_seed,
)
from products.signals.dags.inbox_ranking.common import (
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    ensure_utc,
    owner_tags,
    partition_def,
    partition_object_key,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.queries import LABELS_TEAM_ID, labels_team

INPUTS_TABLE = "activity_summary_inputs"
COST_PROJECTION_TABLE = "activity_summary_cost_projection"

COHORT_EMAIL_DOMAIN = "@posthog.com"

_TIMESTAMP = pa.timestamp("us", tz="UTC")

_INPUTS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("user_id", pa.int64()),
    ("window_start", _TIMESTAMP),
    ("window_end", _TIMESTAMP),
    ("n_mcp_sessions", pa.int32()),
    ("n_ai_conversations", pa.int32()),
    ("rendered_input", pa.string()),
    ("input_chars", pa.int32()),
    ("input_tokens_estimate", pa.int32()),
    ("render_version", pa.int32()),
]
INPUTS_SCHEMA = pa.schema(_INPUTS_FIELDS)

# No free-text column, and none may be added: the projection covers every person in the events.
_COST_PROJECTION_FIELDS: list[tuple[str, pa.DataType]] = [
    ("window_start", _TIMESTAMP),
    ("window_end", _TIMESTAMP),
    ("min_units", pa.int32()),
    ("min_days", pa.int32()),
    ("eligible_pairs", pa.int64()),
    ("input_tokens_p50", pa.int64()),
    ("input_tokens_p90", pa.int64()),
    ("input_tokens_p99", pa.int64()),
    ("updates_per_month", pa.float64()),
    ("input_tokens_per_month", pa.float64()),
    ("output_tokens_per_month", pa.float64()),
    ("projected_monthly_cost_usd", pa.float64()),
    ("calibration_ratio", pa.float64()),
]
COST_PROJECTION_SCHEMA = pa.schema(_COST_PROJECTION_FIELDS)

ASSET_KWARGS: dict[str, Any] = {
    "group_name": "activity_summary",
    "partitions_def": partition_def,
    "tags": owner_tags,
    "retry_policy": dagster.RetryPolicy(max_retries=2, delay=60),
    "pool": "inbox_ranking_etl",
}


class CostProjectionConfig(dagster.Config):
    """Prices are per million tokens and stay unset by default, so a run fills in the current price of
    the model it projects for. Without both prices the cost column stays null."""

    input_price_per_million_tokens: float | None = None
    output_price_per_million_tokens: float | None = None
    # The previous summary (~400 tokens) and the instructions (~500) that every update sends.
    prompt_overhead_tokens: int = 900
    output_tokens_per_update: int = 500


@frozen
class Window:
    start: datetime.datetime
    end: datetime.datetime


def activity_window(partition_key: str) -> Window:
    """The `WINDOW_DAYS` days that end with the partition day."""
    _, end = snapshot_bounds(partition_key)
    return Window(start=end - datetime.timedelta(days=WINDOW_DAYS), end=end)


def _tag_queries(context: dagster.AssetExecutionContext, query_type: str) -> None:
    tag_queries(product=Product.SIGNALS, feature=Feature.DATA_MODELING, team_id=LABELS_TEAM_ID, query_type=query_type)
    get_query_tags().with_dagster(dagster_tags(context))


def cohort_users(organization_id: Any) -> dict[str, int]:
    """The active members of the organization with a cohort email, keyed by their distinct id."""
    return {
        str(distinct_id): user_id
        for distinct_id, user_id in OrganizationMembership.objects.filter(
            organization_id=organization_id,
            user__is_active=True,
            user__email__iendswith=COHORT_EMAIL_DOMAIN,
            user__distinct_id__isnull=False,
        )
        .exclude(user__distinct_id="")
        .values_list("user__distinct_id", "user_id")
    }


def organization_projects(organization_id: Any) -> dict[str, int]:
    """The organization's teams, keyed by the uuid that the events carry as their project group key."""
    return {
        str(team_uuid): team_id
        for team_id, team_uuid in Team.objects.filter(organization_id=organization_id).values_list("id", "uuid")
    }


@frozen(order=True)
class PairKey:
    """A (project, person) pair as the events name it: the team uuid and the distinct id."""

    project: str
    distinct_id: str


def mcp_sessions_by_pair(rows: list[tuple[Any, ...]]) -> dict[PairKey, list[McpSession]]:
    sessions: dict[PairKey, list[McpSession]] = defaultdict(list)
    for distinct_id, project, _session_key, timestamps, tools, intents in rows:
        calls = tuple(
            McpCall(at=ensure_utc(at) or at, tool=str(tool), intent=str(intent))
            for at, tool, intent in zip(timestamps, tools, intents, strict=True)
        )
        sessions[PairKey(project=str(project), distinct_id=str(distinct_id))].append(McpSession(calls=calls))
    return sessions


def ai_prompts_by_pair(rows: list[tuple[Any, ...]]) -> dict[PairKey, list[AiPrompt]]:
    prompts: dict[PairKey, list[AiPrompt]] = defaultdict(list)
    for distinct_id, project, at, prompt in rows:
        key = PairKey(project=str(project), distinct_id=str(distinct_id))
        prompts[key].append(AiPrompt(at=ensure_utc(at) or at, prompt=str(prompt)))
    return prompts


def input_rows(
    *,
    sessions: dict[PairKey, list[McpSession]],
    prompts: dict[PairKey, list[AiPrompt]],
    users: dict[str, int],
    projects: dict[str, int],
    window: Window,
    partition_key: str,
) -> list[dict[str, Any]]:
    """One row per (project, member) with anything left after the filters."""
    sessions_by_person: dict[str, list[McpSession]] = defaultdict(list)
    for pair, person_sessions in sessions.items():
        sessions_by_person[pair.distinct_id].extend(person_sessions)
    jobs = {distinct_id: job_intents(person_sessions) for distinct_id, person_sessions in sessions_by_person.items()}

    rows: list[dict[str, Any]] = []
    for pair in sorted(sessions.keys() | prompts.keys()):
        user_id = users.get(pair.distinct_id)
        team_id = projects.get(pair.project)
        if user_id is None or team_id is None:
            continue
        rendered = build_input(
            sessions.get(pair, []),
            prompts.get(pair, []),
            jobs=jobs.get(pair.distinct_id, frozenset()),
            as_of=window.end,
            seed=sampling_seed(partition_key, team_id, user_id),
        )
        if rendered is None:
            continue
        rows.append(
            {
                "team_id": team_id,
                "user_id": user_id,
                "window_start": window.start,
                "window_end": window.end,
                "n_mcp_sessions": rendered.n_mcp_sessions,
                "n_ai_conversations": rendered.n_ai_conversations,
                "rendered_input": rendered.text,
                "input_chars": rendered.input_chars,
                "input_tokens_estimate": rendered.input_tokens_estimate,
                "render_version": RENDER_VERSION,
            }
        )
    return rows


@dagster.asset(name=INPUTS_TABLE, **ASSET_KWARGS)
def activity_summary_inputs(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    window = activity_window(partition_key)
    team = labels_team()
    users = cohort_users(team.organization_id)
    projects = organization_projects(team.organization_id)

    _tag_queries(context, "activity_summary_inputs")
    kwargs: dict[str, Any] = {
        "team": team,
        "window_start": window.start,
        "window_end": window.end,
        "distinct_ids": users.keys(),
        "projects": projects.keys(),
    }
    session_rows = queries.input_rows(
        queries.INPUT_MCP_SESSIONS_SQL, query_type="activity_summary_input_mcp_sessions", **kwargs
    )
    prompt_rows = queries.input_rows(
        queries.INPUT_AI_PROMPTS_SQL, query_type="activity_summary_input_ai_prompts", **kwargs
    )

    rows = input_rows(
        sessions=mcp_sessions_by_pair(session_rows),
        prompts=ai_prompts_by_pair(prompt_rows),
        users=users,
        projects=projects,
        window=window,
        partition_key=partition_key,
    )
    bucket = dataset_bucket()
    key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, INPUTS_TABLE, partition_key)
    write_parquet(s3_client(), bucket, key, pa.Table.from_pylist(rows, schema=INPUTS_SCHEMA))
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(rows)),
            "cohort_users": dagster.MetadataValue.int(len(users)),
            "mcp_session_rows": dagster.MetadataValue.int(len(session_rows)),
            "ai_prompt_rows": dagster.MetadataValue.int(len(prompt_rows)),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


def pair_activities(mcp_rows: list[tuple[Any, ...]], ai_rows: list[tuple[Any, ...]]) -> dict[PairKey, PairActivity]:
    """Join the two projection queries on the pair. The key never leaves the run."""
    mcp = {
        PairKey(project=str(project), distinct_id=str(distinct_id)): (int(n), float(chars or 0))
        for distinct_id, project, n, chars in mcp_rows
    }
    ai = {
        PairKey(project=str(project), distinct_id=str(distinct_id)): (int(n), float(chars or 0))
        for distinct_id, project, n, chars in ai_rows
    }
    return {
        key: PairActivity(
            mcp_sessions=mcp.get(key, (0, 0.0))[0],
            mcp_chain_chars=mcp.get(key, (0, 0.0))[1],
            ai_conversations=ai.get(key, (0, 0.0))[0],
            ai_prompt_chars=ai.get(key, (0, 0.0))[1],
        )
        for key in mcp.keys() | ai.keys()
    }


def cohort_calibration(
    activities: dict[PairKey, PairActivity], inputs: pa.Table | None, projects: dict[str, int]
) -> float:
    """The rendered-to-estimated length ratio over the cohort pairs both assets cover."""
    if inputs is None or inputs.num_rows == 0:
        return 1.0
    distinct_ids = {
        user_id: str(distinct_id)
        for user_id, distinct_id in User.objects.filter(id__in=set(inputs.column("user_id").to_pylist()))
        .exclude(distinct_id__isnull=True)
        .values_list("id", "distinct_id")
    }
    team_uuids = {team_id: team_uuid for team_uuid, team_id in projects.items()}
    actual: dict[PairKey, int] = {}
    estimated: dict[PairKey, int] = {}
    for row in inputs.select(["team_id", "user_id", "input_chars"]).to_pylist():
        distinct_id = distinct_ids.get(row["user_id"])
        team_uuid = team_uuids.get(row["team_id"])
        if distinct_id is None or team_uuid is None:
            continue
        pair = PairKey(project=team_uuid, distinct_id=distinct_id)
        if pair not in activities:
            continue
        actual[pair] = row["input_chars"]
        estimated[pair] = estimated_input_chars(activities[pair])
    return calibration_ratio(actual, estimated)


@dagster.asset(name=COST_PROJECTION_TABLE, deps=[INPUTS_TABLE], **ASSET_KWARGS)
def activity_summary_cost_projection(context: dagster.AssetExecutionContext, config: CostProjectionConfig) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    window = activity_window(partition_key)
    team = labels_team()

    _tag_queries(context, "activity_summary_cost_projection")
    kwargs: dict[str, Any] = {"team": team, "window_start": window.start, "window_end": window.end}
    mcp_rows = queries.projection_query_rows(
        queries.PROJECTION_MCP_SQL, query_type="activity_summary_projection_mcp", **kwargs
    )
    ai_rows = queries.projection_query_rows(
        queries.PROJECTION_AI_SQL, query_type="activity_summary_projection_ai", **kwargs
    )
    activities = pair_activities(mcp_rows, ai_rows)

    client = s3_client()
    bucket = dataset_bucket()
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    inputs = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, INPUTS_TABLE, partition_key), ["team_id", "user_id", "input_chars"]
    )
    ratio = cohort_calibration(activities, inputs, organization_projects(team.organization_id))

    rows = [
        {"window_start": window.start, "window_end": window.end, **row}
        for row in projection_rows(
            list(activities.values()),
            ratio=ratio,
            prices=ProjectionPrices(
                prompt_overhead_tokens=config.prompt_overhead_tokens,
                output_tokens_per_update=config.output_tokens_per_update,
                input_price_per_million_tokens=config.input_price_per_million_tokens,
                output_price_per_million_tokens=config.output_price_per_million_tokens,
            ),
        )
    ]
    key = partition_object_key(prefix, COST_PROJECTION_TABLE, partition_key)
    write_parquet(client, bucket, key, pa.Table.from_pylist(rows, schema=COST_PROJECTION_SCHEMA))
    context.add_output_metadata(
        {
            "pairs": dagster.MetadataValue.int(len(activities)),
            "calibration_ratio": dagster.MetadataValue.float(ratio),
            "calibrated_on_inputs": dagster.MetadataValue.bool(inputs is not None and inputs.num_rows > 0),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


activity_summary_job = dagster.define_asset_job(
    name="activity_summary_job",
    selection=[INPUTS_TABLE, COST_PROJECTION_TABLE],
    tags={**owner_tags, "dagster/max_runtime": str(60 * 60)},
)


# Stopped everywhere until someone turns it on: the summaries are an experiment, run by hand for now.
@dagster.schedule(
    cron_schedule="30 3 * * 1",
    job=activity_summary_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def activity_summary_schedule(context: dagster.ScheduleEvaluationContext) -> dagster.RunRequest | dagster.SkipReason:
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=previous_day.isoformat())
