"""One-off Dagster job that deletes UserProductList rows for products a user
hasn't opened in the last 60 days, per (user, team), to simplify sidebars.

"Usage" comes from PostHog's own self-capture ``$pageview`` events, which land
in US ClickHouse under team 2 for both US and EU app traffic - so instead of
querying ClickHouse from each region's Dagster, the aggregation below is run
once (e.g. via Metabase), and the resulting CSV(s) are uploaded to the private
scratchpad S3 bucket in each region. Their ``s3://bucket/key`` paths are passed
to the job, which reads them straight from S3 with Dagster's read-only bucket
grant (no public URLs, no pre-signed links). No schedule: launch manually from
the Dagster UI, with `dry_run: true` (the default) first to review the run
metadata.

The aggregation query, ready to copy-run against US prod (team 2). The
``seg1 IN (...)`` whitelist keeps non-product pages (settings, persons,
activity, onboarding, ...) out of the export; it's kept in lockstep with
``URL_KEY_TO_PRODUCT_PATH`` by ``test_docstring_query_whitelist_is_current``.
The INTERVAL must be at least ``window_days`` (rows older than the job's
window are dropped at parse time, so a wider SQL window is fine; a narrower
one would make used products look unused):

    WITH
        extract(`mat_$pathname`, '^/project/\\d+/([^/?#]+)') AS seg1,
        extract(`mat_$pathname`, '^/project/\\d+/[^/?#]+/([^/?#]+)') AS seg2
    SELECT
        distinct_id,
        toInt64OrZero(extract(`mat_$pathname`, '^/project/(\\d+)')) AS browsed_team_id,
        if(seg1 IN ('ai-observability', 'ai-evals'), concat(seg1, '/', seg2), seg1) AS url_key,
        max(timestamp) AS last_seen
    FROM events
    WHERE team_id = 2
      AND event = '$pageview'
      AND timestamp >= now() - INTERVAL 60 DAY
      AND `mat_$pathname` LIKE '/project/%'
      AND seg1 IN (
        'ai-evals', 'ai-gateway', 'ai-observability', 'business-knowledge', 'code_review',
        'customer_analytics', 'dashboard', 'data-ops', 'early_access_features', 'endpoints',
        'engineering-analytics', 'error_tracking', 'experiments', 'feature_flags', 'heatmaps',
        'identity-matching', 'insights', 'links', 'live-debugger', 'logs', 'marketing',
        'mcp-analytics', 'metrics', 'notebooks', 'product_tours', 'prompt-management', 'pulse',
        'replay', 'replay-vision', 'revenue_analytics', 'skills', 'sql', 'support', 'surveys',
        'tasks', 'toolbar', 'tracing', 'user_research', 'visual_review', 'web', 'web-scripts',
        'workflows'
      )
    GROUP BY distinct_id, browsed_team_id, url_key
    HAVING browsed_team_id > 0

If the result exceeds the exporter's row cap (Metabase caps CSVs around 1M
rows), partition it into N non-overlapping exports by adding
``AND modulo(sipHash64(distinct_id), N) = i`` (i in 0..N-1) to the WHERE
clause and pass every file's S3 path to the job.

Files are processed one at a time, so memory stays O(largest file): only one
file's usage dict is held at any point. ASSUMPTION (trusted, not re-verified
by the job): the files partition users - the ``sipHash64(distinct_id)`` split
above guarantees each user's complete usage sits in exactly one file. That is
what makes per-file pruning decision-safe; files split any other way (by
time, by team) could hold partial usage, making used products look unused.

``/project/<id>`` in app pathnames is the team id (the frontend builds it from
``getCurrentTeamId()``), and event ``distinct_id`` equals ``User.distinct_id``
(``posthog.identify(user.distinct_id)``), so CSV rows join straight onto
``UserProductList`` rows in either region's Postgres.
"""

import csv
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from urllib.parse import urlparse

from django.db import connections
from django.utils import timezone

import dagster
import pydantic

from posthog.dags.common import JobOwners
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.user import User

TEAMS_PER_CONNECTION_CYCLE = 500
# Stay well under Postgres' 65535 bind-parameter cap for IN (...) queries.
SQL_IN_BATCH_SIZE = 10_000
# If a file's oldest kept usage row is much newer than the cutoff, the SQL
# window was probably narrower than window_days (see module docstring).
WINDOW_COVERAGE_SLACK = timedelta(days=7)

# URL key -> UserProductList.product_path. Keys are the first pathname segment
# after `/project/<team_id>/`, except under `ai-observability` and `ai-evals`,
# where several products share the first segment and the key keeps two segments.
# Authored from each product's `treeItemsProducts` href in products/*/manifest.tsx;
# `test_every_product_is_classified` guards against drift as products are
# added/renamed.
URL_KEY_TO_PRODUCT_PATH: dict[str, str] = {
    "ai-gateway": "AI gateway",
    # `ai-observability/*` defaults to LLM analytics (dashboard, traces,
    # generations, users, ...); playground and clusters are their own products.
    "ai-observability": "LLM analytics",
    "ai-observability/playground": "Playground",
    "ai-observability/clusters": "Clusters",
    "ai-evals/datasets": "Datasets",
    "ai-evals/evaluations": "Evaluations",
    "ai-evals/taggers": "Taggers",
    "prompt-management": "Prompts",
    "business-knowledge": "Business knowledge",
    "web-scripts": "Web scripts",
    "support": "Support",
    "customer_analytics": "Customer analytics",
    "dashboard": "Dashboards",
    "sql": "SQL editor",
    "data-ops": "Data warehouse",
    "early_access_features": "Early access features",
    "endpoints": "Endpoints",
    "engineering-analytics": "Engineering analytics",
    "error_tracking": "Error tracking",
    "experiments": "Experiments",
    "feature_flags": "Feature flags",
    "identity-matching": "Identity matching",
    "links": "Links",
    "live-debugger": "Live Debugger",
    "logs": "Logs",
    "marketing": "Marketing analytics",
    "mcp-analytics": "MCP analytics",
    "metrics": "Metrics",
    "tasks": "Tasks",
    "insights": "Product analytics",
    "notebooks": "Notebooks",
    "product_tours": "Product tours",
    "pulse": "Pulse",
    "replay": "Session replay",
    "heatmaps": "Heatmaps",
    "replay-vision": "Replay vision",
    "revenue_analytics": "Revenue analytics",
    "code_review": "Code review",
    "skills": "Skills",
    "surveys": "Surveys",
    "toolbar": "Toolbar",
    "tracing": "Tracing",
    "user_research": "User research",
    "visual_review": "Visual review",
    "web": "Web analytics",
    "workflows": "Workflows",
}

# Products with no URL key: we can't observe their usage, so their rows are
# never pruned. Currently every product is mappable; this is the escape hatch
# the drift-guard test points new products at when they genuinely have no
# distinct URL prefix.
UNMAPPED_PRODUCT_PATHS: set[str] = set()

MAPPABLE_PRODUCT_PATHS: set[str] = set(URL_KEY_TO_PRODUCT_PATH.values())

SKIP_RECENT_USER = "recent_user"
SKIP_NO_USAGE = "no_usage"
SKIP_EMPTY_SIDEBAR = "empty_sidebar"


def first_segment_whitelist() -> list[str]:
    """First pathname segments the ClickHouse aggregation should keep.

    Derived from the mapping so the query in the module docstring and the
    parsing below can't drift apart.
    """
    return sorted({key.split("/", 1)[0] for key in URL_KEY_TO_PRODUCT_PATH})


def product_path_for_url_key(url_key: str) -> str | None:
    """Resolve a CSV ``url_key`` to a product path: exact match first, then the
    first segment (the `ai-observability/*` -> LLM analytics fallback)."""
    exact = URL_KEY_TO_PRODUCT_PATH.get(url_key)
    if exact is not None:
        return exact
    return URL_KEY_TO_PRODUCT_PATH.get(url_key.split("/", 1)[0])


def usage_csv_reader(lines: Iterable[str]) -> csv.DictReader:
    """DictReader over a usage CSV, validating the expected header.

    Requires ``distinct_id``, ``browsed_team_id``, ``url_key`` and
    ``last_seen`` (the aggregation query's output). Header cells are
    normalized (whitespace, UTF-8 BOM) so a Metabase-flavored export doesn't
    abort the run on cosmetics.
    """
    reader = csv.DictReader(lines)
    if reader.fieldnames is not None:
        reader.fieldnames = [name.lstrip("\ufeff").strip() for name in reader.fieldnames]
    required = {"distinct_id", "browsed_team_id", "url_key", "last_seen"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError(f"Usage CSV must have columns {sorted(required)}, got {reader.fieldnames}")
    return reader


def _parse_last_seen(raw: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat((raw or "").strip())
    except ValueError:
        return None
    # ClickHouse exports UTC timestamps without an offset.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, kw_only=True)
class ParsedUsageFile:
    # team_id -> distinct_id -> product paths used within the window
    usage: dict[int, dict[str, set[str]]]
    # Oldest kept last_seen; much newer than the cutoff suggests the SQL
    # window was narrower than window_days.
    oldest_last_seen: datetime | None
    stale_rows_dropped: int


def parse_usage_csv(
    lines: Iterable[str],
    allowed_team_ids: set[int],
    cutoff: datetime,
) -> ParsedUsageFile:
    """Fold one CSV's rows into per-team usage.

    Drops rows for teams outside ``allowed_team_ids`` (the other region,
    deleted teams), unmappable url_keys, and rows whose ``last_seen`` is older
    than ``cutoff`` - that makes ``window_days`` authoritative even when the
    SQL export used a wider window. Rows with an unparseable ``last_seen`` are
    kept (counting usage we can't date is the fail-closed direction: it can
    only prevent deletions).
    """
    usage: dict[int, dict[str, set[str]]] = {}
    oldest_last_seen: datetime | None = None
    stale_rows_dropped = 0

    for row in usage_csv_reader(lines):
        try:
            team_id = int(row["browsed_team_id"])
        except (TypeError, ValueError):
            continue
        if team_id not in allowed_team_ids:
            continue
        product_path = product_path_for_url_key(row["url_key"])
        if product_path is None:
            continue
        distinct_id = row["distinct_id"]
        if not distinct_id:
            continue
        last_seen = _parse_last_seen(row.get("last_seen"))
        if last_seen is not None:
            if last_seen < cutoff:
                stale_rows_dropped += 1
                continue
            if oldest_last_seen is None or last_seen < oldest_last_seen:
                oldest_last_seen = last_seen
        usage.setdefault(team_id, {}).setdefault(distinct_id, set()).add(product_path)

    return ParsedUsageFile(usage=usage, oldest_last_seen=oldest_last_seen, stale_rows_dropped=stale_rows_dropped)


@dataclass(frozen=True, kw_only=True)
class ProductListRow:
    """The slice of a UserProductList row the prune decision needs."""

    id: str
    product_path: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class PruneDecision:
    # Why the (user, team) pair was skipped wholesale, or None when pruning applies.
    skip_reason: str | None = None
    rows: list[ProductListRow] = field(default_factory=list)


def select_rows_to_prune(
    rows: list[ProductListRow],
    *,
    user_date_joined: datetime,
    used_paths: set[str] | None,
    cutoff: datetime,
) -> PruneDecision:
    """Decide what to delete for one (user, team).

    ``used_paths`` is the user's mapped usage on this team (``None`` == no
    usage entry at all). Whole-user skips: joined after the cutoff (no time to
    use anything yet), zero observed pageviews (adblock, API-only,
    anonymous-only - absence of data, not absence of usage), and the
    never-empty guard (pruning must not leave a bare sidebar). Only enabled
    rows are candidates - disabled rows are already out of the sidebar and
    record an intentional user choice we want to keep. A row is pruned when
    it's old enough to have been used, its product is measurable, and the
    product wasn't opened in the window.
    """
    if user_date_joined >= cutoff:
        return PruneDecision(skip_reason=SKIP_RECENT_USER)
    if not used_paths:
        return PruneDecision(skip_reason=SKIP_NO_USAGE)

    to_delete = [
        row
        for row in rows
        if row.enabled
        and row.created_at < cutoff
        and row.product_path in MAPPABLE_PRODUCT_PATHS
        and row.product_path not in used_paths
    ]

    enabled_count = sum(1 for row in rows if row.enabled)
    if to_delete and enabled_count == len(to_delete):
        return PruneDecision(skip_reason=SKIP_EMPTY_SIDEBAR)

    return PruneDecision(rows=to_delete)


class PruneConfig(dagster.Config):
    """Configuration for the one-off unused-product pruning run."""

    usage_csv_s3_paths: list[str] = pydantic.Field(
        description=(
            "S3 path(s) (s3://bucket/key) of CSV export(s) of the usage aggregation query "
            "(columns: distinct_id, browsed_team_id, url_key, last_seen), uploaded to the private "
            "scratchpad bucket. Multiple files MUST partition users by distinct_id (see module "
            "docstring) - the job trusts this"
        ),
    )
    dry_run: bool = pydantic.Field(
        default=True,
        description="When true (default), only report what would be deleted",
    )
    window_days: int = pydantic.Field(
        default=60,
        description=(
            "Usage window in days; the aggregation query's INTERVAL must be at least this wide "
            "(older rows are dropped at parse time). Also the minimum age of users and rows "
            "considered for pruning"
        ),
    )


def _iter_csv_lines(s3_client, s3_path: str) -> Iterator[str]:
    """Stream a usage CSV out of S3 one line at a time (keeps memory O(line))."""
    parsed = urlparse(s3_path)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 path scheme: {s3_path}. Expected s3://bucket/key")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 path: {s3_path}. Expected s3://bucket/key")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    for line in response["Body"].iter_lines():
        yield line.decode("utf-8")


T = TypeVar("T")


def _in_batches(items: list[T], size: int = SQL_IN_BATCH_SIZE) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dagster.op(
    retry_policy=dagster.RetryPolicy(
        max_retries=3,
        delay=30,
        backoff=dagster.Backoff.EXPONENTIAL,
        jitter=dagster.Jitter.FULL,
    )
)
def prune_unused_user_products(
    context: dagster.OpExecutionContext, config: PruneConfig, s3: dagster.ResourceParam
) -> None:
    """Retrying the whole op is safe: deletions are idempotent (already-deleted
    rows just aren't matched again)."""
    if not config.usage_csv_s3_paths:
        raise dagster.Failure("usage_csv_s3_paths cannot be empty")

    s3_client = s3.get_client()
    cutoff = timezone.now() - timedelta(days=config.window_days)

    # Scope everything to teams that actually have sidebar rows in this region's Postgres;
    # CSV rows for the other region's team ids are dropped.
    allowed_team_ids = set(UserProductList.objects.values_list("team_id", flat=True).distinct())
    context.log.info(f"{len(allowed_team_ids)} teams have UserProductList rows")

    users_evaluated = 0
    skip_counts: Counter[str] = Counter()
    rows_examined = 0
    rows_deleted = 0
    stale_rows_dropped = 0
    deleted_by_product: Counter[str] = Counter()
    teams_swept: set[int] = set()

    # One file at a time keeps memory at O(largest file); see the module
    # docstring for the partitioning assumption that makes this decision-safe.
    for s3_path in config.usage_csv_s3_paths:
        context.log.info(f"Reading usage CSV from S3: {s3_path}")
        parsed = parse_usage_csv(_iter_csv_lines(s3_client, s3_path), allowed_team_ids, cutoff)
        usage = parsed.usage
        stale_rows_dropped += parsed.stale_rows_dropped
        context.log.info(f"File covers {len(usage)} teams, {sum(len(v) for v in usage.values())} (team, user) pairs")
        if parsed.oldest_last_seen is not None and parsed.oldest_last_seen > cutoff + WINDOW_COVERAGE_SLACK:
            # Can't be a hard failure: a legitimately scoped export (few teams,
            # active users only) also has no usage near the cutoff boundary.
            context.log.warning(
                f"Oldest usage in {s3_path} is {parsed.oldest_last_seen.isoformat()}, well inside the "
                f"{config.window_days}-day window ending {cutoff.isoformat()}. If this is a full export, "
                "the SQL INTERVAL was likely narrower than window_days and used products would look unused."
            )

        for team_index, team_id in enumerate(sorted(usage)):
            teams_swept.add(team_id)
            team_usage = usage[team_id]

            # Resolve only the users with usage in this file; everyone else in the
            # team is untouched by definition, so their rows are never fetched.
            # Users we can't resolve (deleted, NULL distinct_id) or whose usage
            # sits in another file simply don't match here - fail closed, counted
            # in aggregate as user_team_pairs_untouched below.
            users_by_id: dict[int, dict] = {}
            for distinct_id_batch in _in_batches(list(team_usage.keys())):
                users_by_id.update(
                    (user["id"], user)
                    for user in User.objects.filter(distinct_id__in=distinct_id_batch).values(
                        "id", "distinct_id", "date_joined"
                    )
                )
            if not users_by_id:
                continue

            rows_by_user: dict[int, list[ProductListRow]] = {}
            for user_id_batch in _in_batches(list(users_by_id.keys())):
                team_rows = UserProductList.objects.filter(team_id=team_id, user_id__in=user_id_batch).values_list(
                    "id", "user_id", "product_path", "enabled", "created_at"
                )
                for row_id, user_id, product_path, enabled, created_at in team_rows:
                    rows_examined += 1
                    rows_by_user.setdefault(user_id, []).append(
                        ProductListRow(
                            id=str(row_id), product_path=product_path, enabled=enabled, created_at=created_at
                        )
                    )

            team_ids_to_delete: list[str] = []
            for user_id, user_rows in rows_by_user.items():
                user = users_by_id[user_id]

                # Files partition users by distinct_id (module-docstring
                # assumption), so each (user, team) is evaluated in exactly one
                # file and counters never double-count.
                decision = select_rows_to_prune(
                    user_rows,
                    user_date_joined=user["date_joined"],
                    used_paths=team_usage[user["distinct_id"]],
                    cutoff=cutoff,
                )
                users_evaluated += 1
                if decision.skip_reason is not None:
                    skip_counts[decision.skip_reason] += 1
                    continue

                for row in decision.rows:
                    deleted_by_product[row.product_path] += 1
                team_ids_to_delete.extend(row.id for row in decision.rows)

            if team_ids_to_delete:
                rows_deleted += len(team_ids_to_delete)
                if not config.dry_run:
                    for delete_batch in _in_batches(team_ids_to_delete):
                        # Re-check enabled at delete time: a row a user disables
                        # between the read above and here records an intentional
                        # choice we must not delete.
                        UserProductList.objects.filter(id__in=delete_batch, enabled=True).delete()

            if (team_index + 1) % TEAMS_PER_CONNECTION_CYCLE == 0:
                context.log.info(
                    f"Progress: {team_index + 1}/{len(usage)} teams in current file, {users_evaluated} users, "
                    f"{rows_deleted} rows {'would be ' if config.dry_run else ''}deleted"
                )
                # Release per-connection buffers periodically to keep RSS flat
                # across the full team sweep.
                connections.close_all()

    # Everything not evaluated was left untouched: pairs with no usage in any
    # file, unresolvable identities, and pairs in teams with no usage at all.
    # Served by the (team_id, user_id) index, so one index-only scan.
    total_pairs = UserProductList.objects.values("team_id", "user_id").distinct().count()
    pairs_untouched = total_pairs - users_evaluated

    action = "would delete" if config.dry_run else "deleted"
    context.log.info(
        f"Run complete ({'DRY RUN' if config.dry_run else 'LIVE'}): {len(teams_swept)} teams swept, "
        f"{users_evaluated}/{total_pairs} (team, user) pairs evaluated, {rows_examined} rows examined, "
        f"{action} {rows_deleted} rows. Skips: {dict(skip_counts)}"
    )

    context.add_output_metadata(
        {
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
            "teams_swept": dagster.MetadataValue.int(len(teams_swept)),
            "user_team_pairs_total": dagster.MetadataValue.int(total_pairs),
            "user_team_pairs_evaluated": dagster.MetadataValue.int(users_evaluated),
            "user_team_pairs_untouched_no_usage_or_unresolved": dagster.MetadataValue.int(pairs_untouched),
            "users_skipped_recent": dagster.MetadataValue.int(skip_counts[SKIP_RECENT_USER]),
            "users_skipped_empty_sidebar_guard": dagster.MetadataValue.int(skip_counts[SKIP_EMPTY_SIDEBAR]),
            "rows_examined": dagster.MetadataValue.int(rows_examined),
            "stale_usage_rows_dropped": dagster.MetadataValue.int(stale_rows_dropped),
            "rows_deleted" if not config.dry_run else "rows_would_delete": dagster.MetadataValue.int(rows_deleted),
            # Per-product counts surface mapping mistakes: a product with a bad
            # URL key would show an implausibly high delete count here.
            "deleted_by_product": dagster.MetadataValue.json(dict(deleted_by_product.most_common())),
        }
    )


@dagster.job(
    description=(
        "One-off: delete UserProductList rows for products a user hasn't opened in the "
        "usage window, based on a CSV export of self-capture pageview paths."
    ),
    executor_def=dagster.in_process_executor,
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def prune_unused_user_products_job():
    prune_unused_user_products()
