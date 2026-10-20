"""Inputs and a cost projection for per-person activity summaries, with no LLM call.

Two assets on the shared daily partition, each writing Parquet under the dataset prefix:

    activity_summary_inputs/v1/dt=D/           one filtered, rendered input per (project, member)
    activity_summary_cost_projection/v1/dt=D/  eligible pairs, token percentiles and monthly volume

The inputs asset covers only members of the dogfood project's organization with an `@posthog.com`
email, in that organization's own projects, so no customer project's activity gets in. It reads
three sources over the 28 days that end with D: the person's own MCP sessions from the dogfood
project's events, the tasks they started in PostHog AI, Slack or the desktop app, and their
activity log. The projection covers every MCP pair in the events and writes counts only.
"""

import json
import datetime
from collections import defaultdict
from collections.abc import Collection
from typing import Any

from django.db.models.fields.json import KeyTextTransform

import dagster
import pyarrow as pa

from posthog import settings
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries
from posthog.dags.common import dagster_tags
from posthog.dataclasses import frozen
from posthog.models import ActivityLog, OrganizationMembership, Team, User

from products.signals.dags.inbox_ranking.activity_summary import queries
from products.signals.dags.inbox_ranking.activity_summary.render import (
    MAX_ACTIVITY_ROWS_PER_PERSON,
    MAX_TASKS_PER_PERSON,
    RENDER_VERSION,
    WINDOW_DAYS,
    ActivityItem,
    McpCall,
    McpSession,
    PairActivity,
    ProjectionPrices,
    TaskItem,
    build_input,
    calibration_ratio,
    capped_sections_tokens,
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
from products.tasks.backend.facade.user_task_summaries import list_user_task_summaries

INPUTS_TABLE = "activity_summary_inputs"
COST_PROJECTION_TABLE = "activity_summary_cost_projection"

COHORT_EMAIL_DOMAIN = "@posthog.com"
# Tasks a person started: in PostHog AI, in Slack, or by hand in the web or desktop app. Scouts,
# reports and workflows start tasks under a person's name too, and those are not the person's intent.
TASK_ORIGIN_PRODUCTS = ("posthog_ai", "slack", "user_created")

_TIMESTAMP = pa.timestamp("us", tz="UTC")

_INPUTS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("user_id", pa.int64()),
    ("window_start", _TIMESTAMP),
    ("window_end", _TIMESTAMP),
    ("n_tasks", pa.int32()),
    ("n_mcp_sessions", pa.int32()),
    ("n_activity_lines", pa.int32()),
    ("rendered_input", pa.string()),
    ("task_chars", pa.int32()),
    ("mcp_chars", pa.int32()),
    ("activity_chars", pa.int32()),
    ("input_chars", pa.int32()),
    ("input_tokens_estimate", pa.int32()),
    # JSON object of filter rule name to the units or calls it removed for this pair.
    ("drops", pa.string()),
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
    # The task and activity sections, which the projection does not read. Their caps bound them, and
    # the default is that bound, so the projection errs high.
    capped_sections_tokens: int = capped_sections_tokens()
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


@frozen(order=True)
class MemberProject:
    """A (project, person) pair as Postgres names it: the team id and the user id."""

    team_id: int
    user_id: int


def mcp_sessions_by_pair(rows: list[tuple[Any, ...]]) -> dict[PairKey, list[McpSession]]:
    sessions: dict[PairKey, list[McpSession]] = defaultdict(list)
    for distinct_id, project, _session_key, timestamps, tools, intents in rows:
        calls = tuple(
            McpCall(at=ensure_utc(at) or at, tool=str(tool), intent=str(intent))
            for at, tool, intent in zip(timestamps, tools, intents, strict=True)
        )
        sessions[PairKey(project=str(project), distinct_id=str(distinct_id))].append(McpSession(calls=calls))
    return sessions


def member_tasks(
    user_ids: Collection[int], team_ids: Collection[int], window: Window
) -> dict[MemberProject, list[TaskItem]]:
    """Each member's own tasks, newest `MAX_TASKS_PER_PERSON` per member, keyed by project."""
    tasks: dict[MemberProject, list[TaskItem]] = defaultdict(list)
    for user_id in user_ids:
        for task in list_user_task_summaries(
            team_ids=team_ids,
            user_id=user_id,
            start=window.start,
            end=window.end,
            origin_products=TASK_ORIGIN_PRODUCTS,
            limit=MAX_TASKS_PER_PERSON,
        ):
            tasks[MemberProject(team_id=task.team_id, user_id=user_id)].append(
                TaskItem(
                    at=ensure_utc(task.created_at) or task.created_at,
                    title=task.title,
                    summary=task.summary,
                    tags=task.tags,
                )
            )
    return tasks


def member_activity(
    user_ids: Collection[int], team_ids: Collection[int], window: Window
) -> dict[MemberProject, list[ActivityItem]]:
    """Each member's own activity log rows, newest `MAX_ACTIVITY_ROWS_PER_PERSON` per member.

    System rows and rows written while someone impersonated the member are not the member's."""
    activity: dict[MemberProject, list[ActivityItem]] = defaultdict(list)
    for user_id in user_ids:
        rows = (
            ActivityLog.objects.filter(
                team_id__in=list(team_ids),
                user_id=user_id,
                created_at__gte=window.start,
                created_at__lt=window.end,
            )
            .exclude(is_system=True)
            .exclude(was_impersonated=True)
            .order_by("-created_at")
            .annotate(name=KeyTextTransform("name", "detail"))
            .values("team_id", "scope", "activity", "client", "created_at", "name")[:MAX_ACTIVITY_ROWS_PER_PERSON]
        )
        for row in rows:
            activity[MemberProject(team_id=row["team_id"], user_id=user_id)].append(
                ActivityItem(
                    at=ensure_utc(row["created_at"]) or row["created_at"],
                    scope=row["scope"],
                    activity=row["activity"],
                    name=row["name"],
                    client=row["client"],
                )
            )
    return activity


def input_rows(
    *,
    sessions: dict[PairKey, list[McpSession]],
    tasks: dict[MemberProject, list[TaskItem]],
    activity: dict[MemberProject, list[ActivityItem]],
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

    member_sessions: dict[MemberProject, list[McpSession]] = defaultdict(list)
    member_jobs: dict[int, frozenset[tuple[datetime.date, str]]] = {}
    for pair, pair_sessions in sessions.items():
        user_id = users.get(pair.distinct_id)
        team_id = projects.get(pair.project)
        if user_id is None or team_id is None:
            continue
        member_sessions[MemberProject(team_id=team_id, user_id=user_id)].extend(pair_sessions)
        member_jobs[user_id] = jobs.get(pair.distinct_id, frozenset())

    allowed_teams = set(projects.values())
    rows: list[dict[str, Any]] = []
    for member in sorted(member_sessions.keys() | tasks.keys() | activity.keys()):
        if member.team_id not in allowed_teams:
            continue
        rendered = build_input(
            member_sessions.get(member, []),
            tasks.get(member, []),
            activity.get(member, []),
            jobs=member_jobs.get(member.user_id, frozenset()),
            as_of=window.end,
            seed=sampling_seed(partition_key, member.team_id, member.user_id),
        )
        if rendered is None:
            continue
        rows.append(
            {
                "team_id": member.team_id,
                "user_id": member.user_id,
                "window_start": window.start,
                "window_end": window.end,
                "n_tasks": rendered.n_tasks,
                "n_mcp_sessions": rendered.n_mcp_sessions,
                "n_activity_lines": rendered.n_activity_lines,
                "rendered_input": rendered.text,
                "task_chars": rendered.task_chars,
                "mcp_chars": rendered.mcp_chars,
                "activity_chars": rendered.activity_chars,
                "input_chars": rendered.input_chars,
                "input_tokens_estimate": rendered.input_tokens_estimate,
                "drops": json.dumps(rendered.drops, sort_keys=True),
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
    session_rows = queries.input_rows(
        queries.INPUT_MCP_SESSIONS_SQL,
        query_type="activity_summary_input_mcp_sessions",
        team=team,
        window_start=window.start,
        window_end=window.end,
        distinct_ids=users.keys(),
        projects=projects.keys(),
    )
    tasks = member_tasks(users.values(), projects.values(), window)
    activity = member_activity(users.values(), projects.values(), window)

    rows = input_rows(
        sessions=mcp_sessions_by_pair(session_rows),
        tasks=tasks,
        activity=activity,
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
            "task_pairs": dagster.MetadataValue.int(len(tasks)),
            "activity_pairs": dagster.MetadataValue.int(len(activity)),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


def pair_activities(mcp_rows: list[tuple[Any, ...]]) -> dict[PairKey, PairActivity]:
    """The projection query's rows keyed by pair. The key never leaves the run."""
    return {
        PairKey(project=str(project), distinct_id=str(distinct_id)): PairActivity(
            mcp_sessions=int(sessions), mcp_avg_line_chars=float(chars or 0)
        )
        for distinct_id, project, sessions, chars in mcp_rows
    }


def cohort_calibration(
    activities: dict[PairKey, PairActivity], inputs: pa.Table | None, projects: dict[str, int]
) -> float:
    """The rendered-to-estimated MCP section length ratio over the cohort pairs both assets cover."""
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
    for row in inputs.select(["team_id", "user_id", "mcp_chars"]).to_pylist():
        distinct_id = distinct_ids.get(row["user_id"])
        team_uuid = team_uuids.get(row["team_id"])
        if distinct_id is None or team_uuid is None or not row["mcp_chars"]:
            continue
        pair = PairKey(project=team_uuid, distinct_id=distinct_id)
        if pair not in activities:
            continue
        actual[pair] = row["mcp_chars"]
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
    mcp_rows = queries.projection_query_rows(
        queries.PROJECTION_MCP_SQL,
        query_type="activity_summary_projection_mcp",
        team=team,
        window_start=window.start,
        window_end=window.end,
    )
    activities = pair_activities(mcp_rows)

    client = s3_client()
    bucket = dataset_bucket()
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    inputs = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, INPUTS_TABLE, partition_key), ["team_id", "user_id", "mcp_chars"]
    )
    ratio = cohort_calibration(activities, inputs, organization_projects(team.organization_id))

    rows = [
        {"window_start": window.start, "window_end": window.end, **row}
        for row in projection_rows(
            list(activities.values()),
            ratio=ratio,
            prices=ProjectionPrices(
                prompt_overhead_tokens=config.prompt_overhead_tokens + config.capped_sections_tokens,
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
