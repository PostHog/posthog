"""Per-person activity summaries: their inputs, a cost projection, the summaries and their vectors.

Four assets on the shared daily partition, each writing Parquet under the dataset prefix:

    activity_summary_inputs/v1/dt=D/           one filtered, rendered input per (project, member)
    activity_summary_cost_projection/v1/dt=D/  eligible pairs, token percentiles and monthly volume
    activity_summaries/v1/dt=D/                one LLM summary per inputs row
    activity_summary_embeddings/v1/dt=D/       one vector per summary, kept past the source table's TTL

The inputs asset covers only members of the dogfood project's organization with an `@posthog.com`
email, in that organization's own projects, so no customer project's activity gets in. It reads
three sources over the 28 days that end with D: the person's own MCP sessions from the dogfood
project's events, the tasks they started in PostHog AI, Slack or the desktop app, and their
activity log. The projection covers every MCP pair in the events and writes counts only.
"""

import json
import time
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
from products.signals.dags.inbox_ranking.activity_summary.embeddings import (
    EMBEDDING_MODEL,
    LandedVector,
    SummaryDocument,
    document_id,
    emit_summary_embedding,
    flush_embedding_requests,
    landed_vectors,
    pending_documents,
)
from products.signals.dags.inbox_ranking.activity_summary.prompt import PROMPT_VERSION
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
from products.signals.dags.inbox_ranking.activity_summary.summaries import (
    DEFAULT_MODEL,
    PIPELINE_DISTINCT_ID,
    STATUS_OK,
    SummaryPrices,
    SummaryRequest,
    gateway_client,
    summarize,
    summarize_all,
    summary_events,
    summary_row,
)
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    PARQUET_PART_NAME,
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    ensure_utc,
    object_row_count,
    owner_tags,
    partition_def,
    partition_object_key,
    partition_write_allowed,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.queries import LABELS_TEAM_ID, labels_team
from products.signals.dags.inbox_ranking.training.telemetry import capture_training_events
from products.tasks.backend.facade.user_task_summaries import list_user_task_summaries

INPUTS_TABLE = "activity_summary_inputs"
COST_PROJECTION_TABLE = "activity_summary_cost_projection"
SUMMARIES_TABLE = "activity_summaries"
SUMMARY_EMBEDDINGS_TABLE = "activity_summary_embeddings"

# The newest earlier summary of a pair counts as its previous summary only within this many days. An
# older one describes work that has gone quiet, so the pair starts over.
PREVIOUS_SUMMARY_MAX_AGE_DAYS = 60

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

_SUMMARIES_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("user_id", pa.int64()),
    # The normalized answer: summary, focus_areas, products and recent_shift. Null when status is failed.
    ("summary_json", pa.string()),
    ("summary_text", pa.string()),
    ("used_previous_summary", pa.bool_()),
    ("model", pa.string()),
    ("prompt_version", pa.int32()),
    ("tokens_in", pa.int64()),
    ("tokens_out", pa.int64()),
    ("latency_ms", pa.int64()),
    ("cost_usd", pa.float64()),
    ("status", pa.string()),
    ("error", pa.string()),
]
SUMMARIES_SCHEMA = pa.schema(_SUMMARIES_FIELDS)

_SUMMARY_EMBEDDINGS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("user_id", pa.int64()),
    ("prompt_version", pa.int32()),
    ("embedding", pa.list_(pa.float32())),
    ("embedding_model", pa.string()),
]
SUMMARY_EMBEDDINGS_SCHEMA = pa.schema(_SUMMARY_EMBEDDINGS_FIELDS)

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


class SummariesConfig(dagster.Config):
    """Prices are per million tokens and stay unset by default, like the cost projection's, so
    `cost_usd` stays null until a run fills in the current price of `model`."""

    model: str = DEFAULT_MODEL
    # Off to compare the stateful and the stateless summaries on the same inputs.
    use_previous_summary: bool = True
    # Puts the summary text and focus topics on the events. Off by default, because an event cannot be
    # edited or deleted the way a partition can.
    capture_summary_text: bool = False
    input_price_per_million_tokens: float | None = None
    output_price_per_million_tokens: float | None = None
    max_concurrency: int = 8


class SummaryEmbeddingsConfig(dagster.Config):
    # How long the asset waits for the embedding worker to write the vectors it asked for. A vector
    # that lands later is picked up by the next materialization of the partition.
    wait_seconds: int = 600
    poll_interval_seconds: int = 30


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


def summary_partitions_before(client, bucket: str, prefix: str, partition_key: str) -> list[str]:
    """The written summaries partitions in the `PREVIOUS_SUMMARY_MAX_AGE_DAYS` before `partition_key`,
    newest first."""
    folder = f"{prefix}/{SUMMARIES_TABLE}/{DATASET_VERSION}/dt="
    earliest = (
        datetime.date.fromisoformat(partition_key) - datetime.timedelta(days=PREVIOUS_SUMMARY_MAX_AGE_DAYS)
    ).isoformat()
    partitions: set[str] = set()
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=folder):
        for item in page.get("Contents", []):
            partition, _, name = item["Key"].removeprefix(folder).partition("/")
            if name == PARQUET_PART_NAME and earliest <= partition < partition_key:
                partitions.add(partition)
    return sorted(partitions, reverse=True)


def usable_summaries(rows: list[dict[str, Any]], wanted: Collection[MemberProject]) -> dict[MemberProject, dict]:
    """The successful summaries among one partition's rows, for the pairs in `wanted`."""
    return {
        member: json.loads(row["summary_json"])
        for row in rows
        if row["status"] == STATUS_OK
        and row["summary_json"]
        and (member := MemberProject(team_id=row["team_id"], user_id=row["user_id"])) in wanted
    }


def previous_summaries(
    client, bucket: str, prefix: str, partition_key: str, pairs: Collection[MemberProject]
) -> dict[MemberProject, dict]:
    """Each pair's summary from the newest earlier partition that holds one for it. Only earlier
    partitions are read, so a re-run of a partition sees the same previous summaries."""
    wanted = set(pairs)
    found: dict[MemberProject, dict] = {}
    for partition in summary_partitions_before(client, bucket, prefix, partition_key):
        if not wanted:
            break
        table = read_parquet_if_exists(
            client,
            bucket,
            partition_object_key(prefix, SUMMARIES_TABLE, partition),
            ["team_id", "user_id", "summary_json", "status"],
        )
        if table is None:
            continue
        newer = usable_summaries(table.to_pylist(), wanted)
        found |= newer
        wanted -= newer.keys()
    return found


@dagster.asset(name=SUMMARIES_TABLE, deps=[INPUTS_TABLE], **ASSET_KWARGS)
def activity_summaries(context: dagster.AssetExecutionContext, config: SummariesConfig) -> None:
    """One LLM summary per `activity_summary_inputs` row, with its tokens, latency and cost.

    A row whose answer stays malformed after one retry, or whose request fails, is written with
    `status = failed`. When every row fails, the asset fails and leaves the partition as it was."""
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    client = s3_client()
    bucket = dataset_bucket()
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    inputs = read_parquet_if_exists(
        client,
        bucket,
        partition_object_key(prefix, INPUTS_TABLE, partition_key),
        ["team_id", "user_id", "rendered_input", "n_tasks", "n_mcp_sessions", "n_activity_lines", "drops"],
    )
    if inputs is None:
        context.log.warning(f"{INPUTS_TABLE} has no object for dt={partition_key}; nothing to summarize")
        return
    input_rows_ = inputs.to_pylist()
    members = [MemberProject(team_id=row["team_id"], user_id=row["user_id"]) for row in input_rows_]
    previous = previous_summaries(client, bucket, prefix, partition_key, members) if config.use_previous_summary else {}
    requests = [
        SummaryRequest(
            team_id=member.team_id,
            user_id=member.user_id,
            rendered_input=row["rendered_input"],
            previous_summary=previous.get(member),
        )
        for member, row in zip(members, input_rows_, strict=True)
    ]

    llm = gateway_client(partition_key)
    as_of = datetime.date.fromisoformat(partition_key)
    outcomes = summarize_all(
        requests, lambda request: summarize(llm, request, model=config.model, as_of=as_of), config.max_concurrency
    )
    prices = SummaryPrices(
        input_price_per_million_tokens=config.input_price_per_million_tokens,
        output_price_per_million_tokens=config.output_price_per_million_tokens,
    )
    rows = [
        summary_row(request, outcome, model=config.model, prices=prices)
        for request, outcome in zip(requests, outcomes, strict=True)
    ]
    failed = sum(1 for row in rows if row["status"] != STATUS_OK)
    if rows and failed == len(rows):
        raise dagster.Failure(
            f"Every summary failed for dt={partition_key}, so the partition was not written",
            metadata={"rows": len(rows), "first_error": str(rows[0]["error"])},
        )

    key = partition_object_key(prefix, SUMMARIES_TABLE, partition_key)
    write_parquet(client, bucket, key, pa.Table.from_pylist(rows, schema=SUMMARIES_SCHEMA))
    capture_training_events(
        context,
        partition_key,
        summary_events(rows, input_rows_, capture_summary_text=config.capture_summary_text),
        distinct_id=PIPELINE_DISTINCT_ID,
    )
    costs = [row["cost_usd"] for row in rows if row["cost_usd"] is not None]
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(rows)),
            "failed": dagster.MetadataValue.int(failed),
            "used_previous_summary": dagster.MetadataValue.int(sum(1 for row in rows if row["used_previous_summary"])),
            "tokens_in": dagster.MetadataValue.int(sum(row["tokens_in"] for row in rows)),
            "tokens_out": dagster.MetadataValue.int(sum(row["tokens_out"] for row in rows)),
            "cost_usd": dagster.MetadataValue.float(sum(costs)) if costs else dagster.MetadataValue.null(),
            "model": dagster.MetadataValue.text(config.model),
            "prompt_version": dagster.MetadataValue.int(PROMPT_VERSION),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


@frozen
class EmbeddingTarget:
    user_id: int
    prompt_version: int
    text: str


def embedding_targets(rows: list[dict[str, Any]], partition_key: str) -> dict[SummaryDocument, EmbeddingTarget]:
    """The successful summaries of a partition, keyed by their embedding document."""
    return {
        SummaryDocument(
            team_id=row["team_id"], document_id=document_id(row["user_id"], partition_key)
        ): EmbeddingTarget(user_id=row["user_id"], prompt_version=row["prompt_version"], text=row["summary_text"])
        for row in rows
        if row["status"] == STATUS_OK and row["summary_text"]
    }


def summary_embedding_rows(
    targets: dict[SummaryDocument, EmbeddingTarget], landed: dict[SummaryDocument, LandedVector]
) -> list[dict[str, Any]]:
    """One row per summary whose vector landed and embeds the summary's current text."""
    rows: list[dict[str, Any]] = []
    for document, target in sorted(targets.items()):
        vector = landed.get(document)
        if vector is None or vector.content != target.text:
            continue
        rows.append(
            {
                "team_id": document.team_id,
                "user_id": target.user_id,
                "prompt_version": target.prompt_version,
                "embedding": vector.embedding,
                "embedding_model": EMBEDDING_MODEL.value,
            }
        )
    return rows


@dagster.asset(
    name=SUMMARY_EMBEDDINGS_TABLE,
    # Reads the summaries partition, and also keeps the vectors out of the LLM step's run pod memory.
    deps=[SUMMARIES_TABLE],
    **ASSET_KWARGS,
)
def activity_summary_embeddings(context: dagster.AssetExecutionContext, config: SummaryEmbeddingsConfig) -> None:
    """The vector of each successful summary, copied out of `document_embeddings`.

    The source table drops a row three months after its timestamp, which is the partition day, so
    this Parquet is the history a backtest reads. Only a summary with no vector yet, or a vector of
    other text, is sent to the worker, so a re-run does not embed the same text twice. A re-run that
    would write fewer rows than the partition holds is refused: past the source TTL, the vectors it
    lacks cannot come back."""
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    client = s3_client()
    bucket = dataset_bucket()
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    summaries = read_parquet_if_exists(
        client,
        bucket,
        partition_object_key(prefix, SUMMARIES_TABLE, partition_key),
        ["team_id", "user_id", "prompt_version", "summary_text", "status"],
    )
    if summaries is None:
        context.log.warning(f"{SUMMARIES_TABLE} has no object for dt={partition_key}; nothing to embed")
        return
    targets = embedding_targets(summaries.to_pylist(), partition_key)
    wanted = {document: target.text for document, target in targets.items()}
    day_start, _ = snapshot_bounds(partition_key)

    landed = landed_vectors(wanted.keys(), day_start)
    pending = pending_documents(wanted, landed)
    emitted = len(pending)
    if pending:
        for document in pending:
            target = targets[document]
            emit_summary_embedding(
                team_id=document.team_id,
                user_id=target.user_id,
                partition_key=partition_key,
                prompt_version=target.prompt_version,
                text=target.text,
                day_start=day_start,
            )
        flush_embedding_requests()
        deadline = time.monotonic() + config.wait_seconds
        while pending and time.monotonic() < deadline:
            time.sleep(config.poll_interval_seconds)
            landed |= landed_vectors(pending, day_start)
            pending = pending_documents({document: wanted[document] for document in pending}, landed)

    rows = summary_embedding_rows(targets, landed)
    key = partition_object_key(prefix, SUMMARY_EMBEDDINGS_TABLE, partition_key)
    existing_rows = object_row_count(client, bucket, key)
    written = partition_write_allowed(existing_rows, len(rows))
    if written:
        write_parquet(client, bucket, key, pa.Table.from_pylist(rows, schema=SUMMARY_EMBEDDINGS_SCHEMA))
    else:
        context.log.warning(
            f"dt={partition_key} already holds {existing_rows} vectors and this run has {len(rows)}; "
            "the partition was not overwritten"
        )
    context.add_output_metadata(
        {
            "summaries": dagster.MetadataValue.int(summaries.num_rows),
            "skipped_failed_summaries": dagster.MetadataValue.int(summaries.num_rows - len(targets)),
            "emitted": dagster.MetadataValue.int(emitted),
            "missing_vectors": dagster.MetadataValue.int(len(pending)),
            "rows": dagster.MetadataValue.int(len(rows)),
            "written": dagster.MetadataValue.bool(written),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


activity_summary_job = dagster.define_asset_job(
    name="activity_summary_job",
    selection=[INPUTS_TABLE, COST_PROJECTION_TABLE, SUMMARIES_TABLE, SUMMARY_EMBEDDINGS_TABLE],
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
