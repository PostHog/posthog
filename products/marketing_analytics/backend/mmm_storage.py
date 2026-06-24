"""Shared S3 persistence layer for the Marketing Mix Modeling (MMM) POC.

Every run of the `mmm_job` Dagster job (products/marketing_analytics/dags/mmm.py) writes its four
result datasets as Parquet to a per-run S3 prefix (`<prefix>/team_<team_id>/<job_id>/...`); nothing
is persisted on the ClickHouse cluster and there are no result tables in Postgres. The read API
(MarketingAnalyticsViewSet) globs those objects back through the `s3(...)` table function and
degrades to an empty result when the team has no objects yet (a glob matching no files returns zero
rows under `s3_throw_on_zero_files_match=0`). Cross-team isolation is enforced by the
`team_<team_id>` path segment: a job_id belonging to another team resolves to a prefix this team
never wrote.

This mirrors identity matching (products/growth/backend/constants.py +
products/growth/dags/identity_matching.py): all S3 I/O is mediated by ClickHouse, and the path
constants, Parquet schemas, and the `s3(...)` argument builder live here (not in the Dagster module)
so the read API can build identical URLs without importing Dagster. The one difference is that MMM
results originate in Python (the PyMC posterior summary), not in a ClickHouse SELECT, so writes use
`INSERT INTO FUNCTION s3(...) SELECT * FROM input('<structure>')` with client-side rows.
"""

import uuid
from functools import partial
from typing import Any, Optional

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import Feature, Product, tags_context

# Dataset path segments under `<prefix>/team_<team_id>/<job_id>/`. Each dataset is a single Parquet
# object (MMM results are kilobytes — a few channels × the modeling window — so unlike identity
# matching there is no multi-part write).
MMM_RUN_META = "run_meta/data.parquet"
MMM_CONTRIBUTIONS = "contributions/data.parquet"
MMM_CURVES = "curves/data.parquet"
MMM_ROI = "roi/data.parquet"

MMM_MODEL_VERSION = "mmm_v1"

# Parquet column schemas — the explicit `structure` argument to every `s3(...)` call. Used
# identically on write and read so ClickHouse never infers schema (a glob matching no objects then
# returns zero rows instead of failing inference — the "no run yet" path). `job_id` is `String`
# because ClickHouse cannot write `UUID` to Parquet. The column order here must match each write's
# row-tuple order, since `INSERT ... SELECT * FROM input(structure)` casts positionally.
MMM_RUN_META_STRUCTURE = """
    job_id String, team_id Int64, status String, model_version String,
    outcome_kind String, outcome_ref String,
    date_from Date, date_to Date, window_weeks UInt32,
    channels Array(String),
    r_squared Float64, mape Float64, divergences UInt32,
    total_budget Float64, computed_at DateTime
"""

# baseline stored as channel = '__baseline__', spend = 0
MMM_CONTRIBUTIONS_STRUCTURE = """
    job_id String, team_id Int64, week Date, channel String,
    spend Float64, contribution Float64, contribution_lower Float64, contribution_upper Float64
"""

MMM_CURVES_STRUCTURE = """
    job_id String, team_id Int64, channel String,
    spend_point Float64, incremental_outcome Float64,
    incremental_lower Float64, incremental_upper Float64
"""

MMM_ROI_STRUCTURE = """
    job_id String, team_id Int64, channel String,
    roi Float64, roi_lower Float64, roi_upper Float64,
    marginal_roi Float64, current_spend Float64, recommended_spend Float64,
    calibrated UInt8
"""

BASELINE_CHANNEL = "__baseline__"
# "degraded" = the fit completed and was persisted, but one or more posterior summaries fell back to
# placeholder/zeroed values (see the Dagster job's _summarize_* helpers); consumers must not trust it.
MMM_RUN_STATUSES = ["ok", "degraded", "insufficient_history", "failed"]

# On a Cloud deployment the scratch bucket must be a dedicated, infra-provided bucket distinct from
# the general object-storage bucket. MARKETING_MMM_S3_BUCKET falls back to OBJECT_STORAGE_BUCKET
# when its env var is unset, so equality on Cloud means the var is missing and every s3() call would
# target the wrong bucket (the app-assets bucket the ClickHouse role cannot access) — a silent
# AccessDenied. Both the Dagster job and the read API check this so a missing env fails loudly.
MARKETING_MMM_S3_UNCONFIGURED_MESSAGE = (
    "MARKETING_MMM_S3_BUCKET is not set on this deployment, so marketing mix modeling falls back to "
    "the general object-storage bucket, which the ClickHouse role cannot access. Set it to the "
    "scratch bucket (the same value as the Dagster deployment) on every deployment that runs the "
    "MMM Dagster job or its read API."
)

# Let a glob matching no objects return zero rows (the "no run yet" path) instead of erroring, and
# cap execution so a hung/slow s3() read can't pin a web worker indefinitely.
_MMM_READ_SETTINGS = {"s3_throw_on_zero_files_match": "0", "max_execution_time": "60"}
# Each write overwrites its own deterministically-named object, so an op retry is idempotent; the
# execution cap stops a hung S3 write from holding the Dagster op slot forever.
_MMM_WRITE_SETTINGS = {"s3_truncate_on_insert": "1", "max_execution_time": "300"}

# Glob for enumerating every run of a team: `<prefix>/team_<team_id>/*/...`.
ALL_RUNS = "*"


def mmm_s3_unconfigured() -> bool:
    """True when the scratch bucket isn't configured on a Cloud deployment (see message above)."""
    return bool(settings.CLOUD_DEPLOYMENT) and settings.MARKETING_MMM_S3_BUCKET == settings.OBJECT_STORAGE_BUCKET


def _validate_job_id(job_id: str) -> str:
    """Guard the one untrusted segment that reaches the `s3()` SQL string. `job_id` is either a run
    UUID or the glob `*`; anything else (a quote, a slash, a path-traversal) could break out of the
    single-quoted SQL literal or escape the team prefix, so reject it here — the shared chokepoint the
    `# nosemgrep` suppressions in read_dataset rely on, regardless of caller (DRF, Dagster, Max tool)."""
    if job_id == ALL_RUNS:
        return job_id
    try:
        return str(uuid.UUID(str(job_id)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"Invalid MMM job_id: must be a UUID or {ALL_RUNS!r}")


def mmm_run_prefix(team_id: int, job_id: str) -> str:
    """S3 key prefix for one run: `<prefix>/team_<team_id>/<job_id>`.

    `job_id` is either a run UUID (string) or the glob `*` to enumerate every run of a team.
    """
    return f"{settings.MARKETING_MMM_S3_PREFIX}/team_{int(team_id)}/{_validate_job_id(job_id)}"


def mmm_s3_args(team_id: int, job_id: str, relative_path: str, structure: str) -> str:
    """Build the argument list for a ClickHouse `s3(...)` call: ``url[, key, secret], 'Parquet', structure``.

    Credentials are emitted only when an endpoint is configured (local/dev/test object storage); on
    prod the endpoint is empty and the cluster reaches the bucket via its attached IAM role, so no
    secret is ever interpolated into SQL. ``team_id`` (int), ``job_id`` (run UUID or ``*``) and
    ``relative_path`` (constant dataset segments) are all trusted, never request input.
    """
    key = f"{mmm_run_prefix(team_id, job_id)}/{relative_path}"
    endpoint = settings.MARKETING_MMM_S3_ENDPOINT
    if endpoint:
        # Local/dev/test S3-compatible storage (SeaweedFS/MinIO): path-style URL including bucket.
        url = f"{endpoint}/{settings.MARKETING_MMM_S3_BUCKET}/{key}"
        creds = f"'{settings.OBJECT_STORAGE_ACCESS_KEY_ID}', '{settings.OBJECT_STORAGE_SECRET_ACCESS_KEY}', "
    else:
        # Prod AWS S3: virtual-hosted-style HTTPS URL; the cluster authenticates via its IAM role.
        url = f"https://{settings.MARKETING_MMM_S3_BUCKET}.s3.{settings.MARKETING_MMM_S3_REGION}.amazonaws.com/{key}"
        creds = ""
    # The structure is wrapped in a single-quoted SQL literal, so escape any single quotes inside
    # column types (e.g. DateTime64(6, 'UTC')) — otherwise they terminate the literal early.
    compact_structure = " ".join(structure.split()).replace("'", "\\'")
    return f"'{url}', {creds}'Parquet', '{compact_structure}'"


def _insert_rows(
    client: Client, *, query: str, rows: list[tuple[Any, ...]], query_settings: dict[str, Any]
) -> list[tuple[Any, ...]]:
    return client.execute(query, rows, settings=query_settings)


def write_dataset(
    cluster: ClickhouseCluster,
    team_id: int,
    job_id: str,
    relative_path: str,
    structure: str,
    rows: list[tuple[Any, ...]],
    query_settings: Optional[dict[str, Any]] = None,
) -> None:
    """Write client-side rows to S3 Parquet via the ClickHouse cluster. No boto3.

    `rows` is a `list[tuple]` matching the structure's column order. Results are kilobytes, so no
    batching/concurrency is needed (unlike identity matching's 10k-row parts). The cluster path runs
    via clickhouse_driver (not `sync_execute`), so it can't read the thread-local query tags directly —
    callers (the Dagster op) pass `query_settings` carrying a `log_comment` (snapshot of the active
    `tags_context` via `settings_with_log_comment`) so the INSERT is still attributed.
    """
    if not rows:
        return
    args = mmm_s3_args(team_id, job_id, relative_path, structure)
    # `input(...)` takes the structure as its own SQL literal — no quote-escaping (none of the MMM
    # structures contain a quote), unlike the s3() structure arg which lives inside a quoted literal.
    compact = " ".join(structure.split())
    query = f"INSERT INTO FUNCTION s3({args}) SELECT * FROM input('{compact}')"
    settings = {**_MMM_WRITE_SETTINGS, **(query_settings or {})}
    cluster.any_host(partial(_insert_rows, query=query, rows=rows, query_settings=settings)).result()


def read_dataset(
    team_id: int,
    job_id: str,
    relative_path: str,
    structure: str,
    columns: list[str],
    where: str = "",
    params: Optional[dict[str, Any]] = None,
) -> list[tuple[Any, ...]]:
    """Read selected columns of one dataset for a run (or all runs when ``job_id == '*'``).

    A glob matching no objects returns zero rows (not an error) via `s3_throw_on_zero_files_match=0`.
    `team_id` stays as a defensive predicate even though the S3 path already scopes the team.
    """
    args = mmm_s3_args(team_id, job_id, relative_path, structure)
    sql = f"SELECT {', '.join(columns)} FROM s3({args}) WHERE team_id = %(team_id)s {where}"  # noqa: S608 — s3() args from team_id (int) and a validated job_id/`*` (see _validate_job_id); columns/where are in-code constants, values parameterized
    # Tag the query with product/feature so it's attributed in ClickHouse resource management — and so
    # it doesn't raise UntaggedQueryError in local dev (DEBUG). Mirrors identity matching's read API.
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY):
        return sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — s3() path from team_id (int) and validated job_id; columns/where are in-code constants, values parameterized
            sql,
            {"team_id": team_id, **(params or {})},
            settings=_MMM_READ_SETTINGS,
            team_id=team_id,
        )
