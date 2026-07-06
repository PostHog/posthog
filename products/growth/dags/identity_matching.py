"""Identity matching: link anonymous distinct_ids to identified persons using first-party signals.

Visits from the same human on different devices/browsers produce unlinked anonymous
distinct_ids, so pre-signup marketing touchpoints (e.g. a paid click on a phone) cannot
be attributed to the signup that happens on another device. This job scores candidate
(orphan distinct_id, identified person) links from signals we already store: shared
IP-days, geo/locale agreement, user-agent and webview signatures, temporal patterns,
path overlap, and campaign continuity.

Ground truth comes from retroactive merges: an orphan that merges into a person *after*
the feature window is, at window end, indistinguishable from a permanent orphan, so those
merges provide labels for training and for precision/recall evaluation without leakage.

The job persists nothing on the ClickHouse cluster: each stage writes its output as Parquet
to a pre-provisioned "scratch" S3 bucket via `INSERT INTO FUNCTION s3(...)`, namespaced per
run (`<prefix>/team_<team_id>/<job_id>/<dataset>/`), and reads it back with the `s3(...)` table
function. Retention is the bucket lifecycle policy's job — there is no MergeTree TTL. It never
writes to the person store: merges are irreversible, links stay reversible and analytics-only.

Environment restrictions: the job processes internal PostHog data that only exists on
Cloud US (team 2). It is not registered on Cloud EU, and on Cloud US it only accepts the
allowed internal teams; local, dev, and self-hosted environments are unrestricted.

Known limitations:
- Merges older than `identity_lookback_days` before the window are not visible, so a
  long-dormant merged distinct_id that reactivates in-window is classified as an orphan.
- IP-based features require `$ip` on events; teams with IP anonymization enabled will
  produce empty IP coverage (surfaced loudly in the run report).
- The Parquet objects store raw IPs; they are internal-only and expire via the scratch
  bucket's lifecycle policy.
"""

import hashlib
import datetime
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from typing import Any

import dagster
import pydantic
import dagster_slack
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment

from products.growth.backend.constants import (
    IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET,
    IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE,
    IDENTITY_MATCHING_DEVICE_DAYS_DATASET,
    IDENTITY_MATCHING_DEVICE_DAYS_STRUCTURE,
    IDENTITY_MATCHING_LINKS_DATASET,
    IDENTITY_MATCHING_LINKS_STRUCTURE,
    IDENTITY_MATCHING_LOGREG_MODEL_VERSION,
    IDENTITY_MATCHING_PERSON_TIMELINE_DATASET,
    IDENTITY_MATCHING_PERSON_TIMELINE_STRUCTURE,
    IDENTITY_MATCHING_RULES_MODEL_VERSION,
    IDENTITY_MATCHING_S3_UNCONFIGURED_MESSAGE,
    identity_matching_dataset_read_args,
    identity_matching_run_prefix,
    identity_matching_s3_args,
    identity_matching_s3_unconfigured,
)

# Click IDs that indicate a paid ad click, a subset of CAMPAIGN_PROPERTIES
# (posthog/taxonomy/taxonomy.py) excluding organic/email params like igshid or mc_cid.
PAID_CLICK_IDS: list[str] = [
    "gclid",
    "gad_source",
    "gclsrc",
    "dclid",
    "gbraid",
    "wbraid",
    "fbclid",
    "msclkid",
    "twclid",
    "li_fat_id",
    "ttclid",
    "rdt_cid",
    "sccid",
]

IDENTITY_EVENTS: list[str] = ["$identify", "$create_alias", "$merge_dangerously"]

# In-app browsers and webviews keep their own cookie jar, so ad clicks that open in them
# are orphaned even on a single device. Byte-identical UA + shared IP is a strong signal.
# Double backslash: ClickHouse string literals unescape \\ to \, yielding the regex wv\).
WEBVIEW_UA_REGEX = r"wv\\)|FBAN|FBAV|Instagram|Line/|MicroMessenger|GSA/"

RULES_MODEL_VERSION = IDENTITY_MATCHING_RULES_MODEL_VERSION
LOGREG_MODEL_VERSION = IDENTITY_MATCHING_LOGREG_MODEL_VERSION

# Numeric pair features, in the column order used for both training and scoring.
PAIR_FEATURE_COLUMNS: list[str] = [
    "shared_ip_days",
    "shared_ips",
    "min_ip_block_size",
    "geo_city_match",
    "timezone_match",
    "language_match",
    "ua_exact_match",
    "orphan_is_webview",
    "device_type_complement",
    "days_overlap",
    "orphan_last_to_anchor_first_s",
    "avg_path_jaccard",
    "orphan_paid_touch",
    "anchor_paid_touch",
]

DEFAULT_RULE_WEIGHTS: dict[str, float] = {
    "shared_ip_day": 1.0,
    "multi_ip": 1.5,
    "small_block": 1.0,
    "geo_city": 0.5,
    "timezone": 0.25,
    "language": 0.25,
    "ua_exact": 2.0,
    "webview_same_ua": 1.5,
    "device_complement": 0.5,
    "path_jaccard": 2.0,
    "paid_continuity": 0.75,
}

# Internal-only data-safety guardrails: the training data lives in the PostHog Cloud US
# internal project (team 2). The job is not registered on Cloud EU at all, and on Cloud US
# it refuses to process any other team. Local, dev, and self-hosted are unrestricted.
PROD_US_ALLOWED_TEAM_IDS: frozenset[int] = frozenset({2})

_ONE_GB = 1024**3


def is_identity_matching_registered() -> bool:
    return settings.CLOUD_DEPLOYMENT != "EU"


def validate_team_allowed(team_id: int) -> None:
    if settings.CLOUD_DEPLOYMENT == "EU":
        raise dagster.Failure("Identity matching does not run on PostHog Cloud EU")
    if settings.CLOUD_DEPLOYMENT == "US" and team_id not in PROD_US_ALLOWED_TEAM_IDS:
        raise dagster.Failure(
            f"On PostHog Cloud US identity matching may only process teams "
            f"{sorted(PROD_US_ALLOWED_TEAM_IDS)}, got team {team_id}"
        )


class IdentityMatchingConfig(dagster.Config):
    team_id: int = pydantic.Field(description="Team whose events are matched.")
    date_start: str = pydantic.Field(description="Feature window start (inclusive), YYYY-MM-DD.")
    date_end: str = pydantic.Field(description="Feature window end (exclusive), YYYY-MM-DD.")
    eval_horizon_days: int = pydantic.Field(
        default=14,
        description="Days after date_end in which merges are used as evaluation labels.",
    )
    identity_lookback_days: int = pydantic.Field(
        default=90,
        description="Days before date_start to scan identity events for anchor classification.",
    )
    included_events: list[str] = pydantic.Field(
        default=["$pageview", "$screen", "$identify"],
        description="Events scanned for the device-day index. $identify is included because it "
        "carries the anchor device's IP at the identification moment.",
    )
    ips_per_day_cap: int = pydantic.Field(default=10, description="Max distinct IPs kept per device-day.")
    paths_per_day_cap: int = pydantic.Field(default=50, description="Max distinct pathnames kept per device-day.")
    ip_day_block_cap: int = pydantic.Field(
        default=25,
        description="(ip, day) blocks with more devices than this are excluded from candidate generation.",
    )
    ip_window_device_cap: int = pydantic.Field(
        default=100,
        description="IPs seen with more devices than this over the whole window are excluded "
        "(corporate NAT / CGNAT guard).",
    )
    max_candidates_per_orphan: int = pydantic.Field(default=20, description="Max anchor candidates kept per orphan.")
    max_identity_edges: int = pydantic.Field(default=2_000_000, description="Max identity edges pulled into memory.")
    rule_weights: dict[str, float] = pydantic.Field(
        default=DEFAULT_RULE_WEIGHTS,
        description="Per-signal weights for the rule-based score.",
    )
    rule_min_score: float = pydantic.Field(default=3.0, description="Minimum rule score for a link to be kept.")
    rule_min_margin: float = pydantic.Field(
        default=1.0,
        description="Minimum rule-score margin over the runner-up anchor for a link to be kept.",
    )
    rule_tier_high: float = pydantic.Field(default=6.0, description="Rule score at or above which tier is 'high'.")
    rule_tier_medium: float = pydantic.Field(default=4.0, description="Rule score at or above which tier is 'medium'.")
    rule_thresholds: list[float] = pydantic.Field(
        default=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
        description="Rule-score thresholds for the evaluation sweep.",
    )
    min_training_positives: int = pydantic.Field(
        default=50,
        description="Minimum positive labels required to train the logistic regression.",
    )
    min_training_negatives: int = pydantic.Field(
        default=20,
        description="Minimum hard-negative labels required to train the logistic regression.",
    )
    max_training_rows: int = pydantic.Field(default=500_000, description="Max labeled rows pulled for training.")
    max_scoring_rows: int = pydantic.Field(default=2_000_000, description="Max candidate rows pulled for scoring.")
    weak_negative_sample_ratio: float = pydantic.Field(
        default=3.0,
        description="Unlabeled pairs sampled as weak negatives, per labeled row.",
    )
    prob_thresholds: list[float] = pydantic.Field(
        default=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95],
        description="Probability thresholds for the evaluation sweep.",
    )
    prob_tier_high: float = pydantic.Field(default=0.9, description="Probability at or above which tier is 'high'.")
    prob_tier_medium: float = pydantic.Field(default=0.7, description="Probability at or above which tier is 'medium'.")
    logreg_min_prob: float = pydantic.Field(
        default=0.5,
        description="Minimum predicted probability for a logreg link to be kept (the logreg analogue of rule_min_score).",
    )
    logreg_min_margin: float = pydantic.Field(
        default=0.0,
        description="Minimum probability margin over the runner-up anchor for a logreg link to be kept.",
    )
    query_max_execution_time_seconds: int = pydantic.Field(
        default=60 * 60,
        gt=0,
        description="ClickHouse max_execution_time per query — ceiling that aborts a runaway query.",
    )
    query_max_memory_usage_gb: int = pydantic.Field(
        default=50,
        gt=0,
        description="ClickHouse max_memory_usage per query, in GB — per-host cap that guards against OOM.",
    )
    query_external_spill_gb: int = pydantic.Field(
        default=25,
        gt=0,
        description="GROUP BY / ORDER BY / JOIN memory in GB past which a query spills to disk "
        "instead of erroring. Must stay below query_max_memory_usage_gb to take effect before the cap.",
    )
    slack_channel: str = pydantic.Field(
        default="C0BCESDFRLZ",
        description="Slack channel ID for the success report. Empty disables the notification. The "
        "Dagster Slack bot must be a member of the channel. Only posts on Cloud deployments.",
    )

    @pydantic.model_validator(mode="after")
    def check_window(self) -> "IdentityMatchingConfig":
        if datetime.date.fromisoformat(self.date_start) >= datetime.date.fromisoformat(self.date_end):
            raise ValueError("date_start must be before date_end")
        unknown_weights = set(self.rule_weights) - set(DEFAULT_RULE_WEIGHTS)
        if unknown_weights:
            raise ValueError(f"Unknown rule weights: {sorted(unknown_weights)}")
        if self.query_external_spill_gb >= self.query_max_memory_usage_gb:
            raise ValueError(
                f"query_external_spill_gb ({self.query_external_spill_gb}) must be below "
                f"query_max_memory_usage_gb ({self.query_max_memory_usage_gb}) to spill before the cap"
            )
        return self

    def query_guards(self) -> dict[str, str]:
        """ClickHouse per-query guard settings derived from the run config (see _base_settings)."""
        spill_bytes = str(self.query_external_spill_gb * _ONE_GB)
        return {
            "max_execution_time": str(self.query_max_execution_time_seconds),
            "max_memory_usage": str(self.query_max_memory_usage_gb * _ONE_GB),
            "max_bytes_before_external_group_by": spill_bytes,
            "max_bytes_before_external_sort": spill_bytes,
            "distributed_aggregation_memory_efficient": "1",  # memory-efficient GROUP BY over distributed events
            # Let the candidate_pairs hash join spill to a partial-merge join past the same
            # threshold instead of erroring at max_memory_usage — without this, a join heavier than
            # the cap is the one way these guards could break an otherwise-working run.
            "join_algorithm": "auto",
            "max_bytes_in_join": spill_bytes,
        }


@dataclass(frozen=True)
class MatchingRun:
    """Run state threaded through ops: the run's job_id plus the parsed config."""

    job_id: str
    config: IdentityMatchingConfig

    @property
    def date_start(self) -> str:
        return self.config.date_start

    @property
    def date_end(self) -> str:
        return self.config.date_end

    @property
    def edges_start(self) -> str:
        start = datetime.date.fromisoformat(self.config.date_start)
        return (start - datetime.timedelta(days=self.config.identity_lookback_days)).isoformat()

    @property
    def eval_end(self) -> str:
        end = datetime.date.fromisoformat(self.config.date_end)
        return (end + datetime.timedelta(days=self.config.eval_horizon_days)).isoformat()


@dataclass(frozen=True)
class MatchingDataset:
    """A per-run S3 dataset: a folder of one or more Parquet objects under the run prefix.

    `folder` is the path segment under `<prefix>/team_<team_id>/<job_id>/`; `structure` is the
    Parquet column schema, passed as the explicit `structure` arg to every `s3(...)` call so that
    writes cast the projection to fixed column types (replacing the old `INSERT INTO <table>`) and
    reads stay schema-stable. No DDL: there is no table to create, sync, or drop.
    """

    folder: str
    structure: str

    def write_args(self, run: "MatchingRun", filename: str) -> str:
        """`s3(...)` args writing one object `<folder>/<filename>` for this run."""
        return identity_matching_s3_args(run.config.team_id, run.job_id, f"{self.folder}/{filename}", self.structure)

    def read_args(self, run: "MatchingRun") -> str:
        """`s3(...)` args globbing every Parquet object in this dataset for this run."""
        return identity_matching_dataset_read_args(run.config.team_id, run.job_id, self.folder, self.structure)


DEVICE_DAYS = MatchingDataset(IDENTITY_MATCHING_DEVICE_DAYS_DATASET, IDENTITY_MATCHING_DEVICE_DAYS_STRUCTURE)
PERSON_TIMELINE = MatchingDataset(
    IDENTITY_MATCHING_PERSON_TIMELINE_DATASET, IDENTITY_MATCHING_PERSON_TIMELINE_STRUCTURE
)
CANDIDATE_PAIRS = MatchingDataset(
    IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET, IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE
)
LINKS = MatchingDataset(IDENTITY_MATCHING_LINKS_DATASET, IDENTITY_MATCHING_LINKS_STRUCTURE)

# A single Parquet object per SQL-produced dataset; multi-part datasets append `part_<n>`.
SINGLE_OBJECT = "data.parquet"

# `s3_truncate_on_insert` makes each write overwrite its own deterministically-named object, so an
# op retry is idempotent. `s3_throw_on_zero_files_match=0` lets a glob that matches nothing return
# zero rows instead of erroring (the logreg-skipped and no-data paths).


# Per-query guards so a pathological run (e.g. an over-wide window on a large team) degrades or
# aborts on the single host it runs on, rather than pressuring the cluster. The ceilings are
# tunable per run from the Dagster launchpad (IdentityMatchingConfig.query_*); the defaults are
# modeled on the events_backfill_to_duckling job and the working team-2 run sits well under them.
# The external thresholds make large GROUP BY / ORDER BY spill to disk instead of hitting the
# memory cap and erroring, so they only change behavior for queries that would otherwise blow up.
def _base_settings(context: dagster.OpExecutionContext, run: "MatchingRun") -> dict[str, str]:
    return {**settings_with_log_comment(context), **run.config.query_guards()}


def _write_settings(context: dagster.OpExecutionContext, run: "MatchingRun") -> dict[str, str]:
    return {**_base_settings(context, run), "s3_truncate_on_insert": "1"}


def _read_settings(context: dagster.OpExecutionContext, run: "MatchingRun") -> dict[str, str]:
    return {**_base_settings(context, run), "s3_throw_on_zero_files_match": "0"}


# Rows the Python ops build (person_timeline, logreg links) are written in batches as inline
# VALUES. clickhouse_driver's native-block insert path (`INSERT ... VALUES` with a list of tuples
# and nothing after VALUES) hangs against `INSERT INTO FUNCTION s3(...)`; embedding the rows as
# `VALUES (%(..)s), ...` placeholders instead routes through ordinary server-parsed substitution,
# which writes Parquet to s3 reliably. Each batch is one serial round-trip writing one Parquet
# part, so the batch size trades round-trip count (wall-clock) against per-statement size: at 10k
# rows a substituted statement stays a few MB (well under the max_query_size raised below) and
# ~100k AST elements (well under the ~500k cap), while cutting round-trips and part files 10x
# versus 1k. On large teams (team 2) the row count reaches 1-2M, so 1k batches meant thousands of
# serial inserts dominating the op runtime.
_S3_VALUES_BATCH = 10000

# Each batch is an independent INSERT INTO FUNCTION s3 round-trip to its own Parquet part, and
# any_host targets one host, so this many writes run concurrently against that single node. It
# hides the per-statement round-trip latency that dominated the op (1-2M rows = hundreds of parts)
# without flooding the host. Distinct part filenames mean concurrent writes never collide, and
# s3_truncate_on_insert keeps each part idempotent on retry.
_S3_WRITE_CONCURRENCY = 8


def _write_rows_to_s3(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    dataset: "MatchingDataset",
    run: "MatchingRun",
    rows: list[tuple[Any, ...]],
    columns: int,
    filename_prefix: str = "part",
) -> None:
    if not rows:
        return
    query_settings = {**_write_settings(context, run), "max_query_size": "10485760"}
    batches = [rows[offset : offset + _S3_VALUES_BATCH] for offset in range(0, len(rows), _S3_VALUES_BATCH)]

    def _write_part(part: int, batch: list[tuple[Any, ...]]) -> None:
        placeholders: list[str] = []
        parameters: dict[str, Any] = {}
        for i, row in enumerate(batch):
            keys = [f"v{i}_{j}" for j in range(columns)]
            placeholders.append("(" + ", ".join(f"%({key})s" for key in keys) + ")")
            parameters.update(zip(keys, row, strict=True))
        query = (
            f"INSERT INTO FUNCTION s3({dataset.write_args(run, f'{filename_prefix}_{part}.parquet')}) "
            f"VALUES {', '.join(placeholders)}"
        )
        cluster.any_host(partial(_execute, query=query, parameters=parameters, query_settings=query_settings)).result()

    # Write the first part serially to prime the host connection pool: cluster.any_host creates the
    # pool lazily on first use (a check-then-set on its host->pool map), so doing one write before
    # fanning out avoids a creation race when the rest run concurrently.
    _write_part(0, batches[0])
    if len(batches) == 1:
        return
    with ThreadPoolExecutor(max_workers=_S3_WRITE_CONCURRENCY) as executor:
        futures = [executor.submit(_write_part, part, batch) for part, batch in enumerate(batches[1:], start=1)]
        try:
            for future in as_completed(futures):
                future.result()  # surface the first failure; a retry overwrites parts idempotently
        except Exception:
            # Cancel queued (not-yet-started) batches so the op fails fast instead of waiting for
            # every remaining write — the `with` block's shutdown(wait=True) would otherwise let
            # all submitted futures run before the exception surfaces.
            for pending in futures:
                pending.cancel()
            raise


def _prop(name: str) -> str:
    return f"JSONExtractString(properties, '{name}')"


def _any_nonempty(expr: str) -> str:
    return f"anyIf({expr}, {expr} != '')"


def _first_clid_kind_expr() -> str:
    branches = ", ".join(f"{_prop(clid)} != '', '{clid}'" for clid in PAID_CLICK_IDS)
    return f"multiIf({branches}, '')"


def _has_paid_clid_expr() -> str:
    return " OR ".join(f"{_prop(clid)} != ''" for clid in PAID_CLICK_IDS)


@dagster.op
def prepare_run(
    context: dagster.OpExecutionContext,
    config: IdentityMatchingConfig,
) -> MatchingRun:
    """Validate the team gate and seed the run state. No tables are created — each stage writes
    Parquet to its own S3 prefix, and the first real write surfaces any auth/bucket error."""
    validate_team_allowed(config.team_id)
    # Fail before any S3 I/O if the scratch bucket env is missing, rather than writing to the
    # wrong (fallback) bucket and surfacing an opaque AccessDenied on the first write.
    if identity_matching_s3_unconfigured():
        raise dagster.Failure(IDENTITY_MATCHING_S3_UNCONFIGURED_MESSAGE)
    run = MatchingRun(job_id=context.run.run_id, config=config)
    context.log.info(
        f"Run {run.job_id}: team {config.team_id}, window [{run.date_start}, {run.date_end}), "
        f"edges from {run.edges_start}, eval until {run.eval_end}; "
        f"writing to s3 prefix {identity_matching_run_prefix(config.team_id, run.job_id)}/"
    )
    # Training labels come from merges in [date_end, eval_end). If that horizon has not elapsed,
    # those merges have not happened yet, so the logistic regression sees no labels and skips —
    # which reads as a silent failure. Warn rather than fail: the rule model needs no labels.
    now = datetime.datetime.now(datetime.UTC)
    eval_end = datetime.datetime.fromisoformat(run.eval_end).replace(tzinfo=datetime.UTC)
    if eval_end > now:
        window_end = datetime.datetime.fromisoformat(run.date_end).replace(tzinfo=datetime.UTC)
        if window_end >= now:
            context.log.warning(
                f"Evaluation horizon [{run.date_end}, {run.eval_end}) is entirely in the future "
                f"(today is {now.date().isoformat()}): no post-window merges exist yet, so the logistic "
                f"regression will have no training labels and will skip. Re-run with date_end at least "
                f"eval_horizon_days ({config.eval_horizon_days}) in the past to train it."
            )
        else:
            context.log.warning(
                f"Evaluation horizon ends {run.eval_end}, after today ({now.date().isoformat()}): labels "
                f"are only partially observed, so logistic regression will undercount positives. Re-run "
                f"after {run.eval_end} for a complete evaluation."
            )
    return run


@dagster.op
def build_device_day_index(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: MatchingRun,
) -> MatchingRun:
    """Aggregate per-(distinct_id, day) signals from events into the device-day index."""
    config = run.config
    query = f"""
        INSERT INTO FUNCTION s3({DEVICE_DAYS.write_args(run, SINGLE_OBJECT)})
        SELECT
            %(job_id)s,
            team_id,
            distinct_id,
            toDate(timestamp) AS day,
            groupUniqArrayIf(%(ips_cap)s)({_prop("$ip")}, {_prop("$ip")} != ''),
            {_any_nonempty(_prop("$browser"))},
            {_any_nonempty(_prop("$os"))},
            {_any_nonempty(_prop("$device_type"))},
            {_any_nonempty(_prop("$timezone"))},
            {_any_nonempty(_prop("$browser_language"))},
            {_any_nonempty(_prop("$raw_user_agent"))},
            {_any_nonempty(_prop("$geoip_city_name"))},
            {_any_nonempty(_prop("$geoip_subdivision_1_code"))},
            {_any_nonempty(_prop("$geoip_postal_code"))},
            groupUniqArrayIf(%(paths_cap)s)({_prop("$pathname")}, event = '$pageview' AND {_prop("$pathname")} != ''),
            argMinIf({_prop("$referring_domain")}, timestamp, {_prop("$referring_domain")} != ''),
            argMinIf({_prop("utm_source")}, timestamp, {_prop("utm_source")} != ''),
            argMinIf({_prop("utm_medium")}, timestamp, {_prop("utm_medium")} != ''),
            argMinIf({_prop("utm_campaign")}, timestamp, {_prop("utm_campaign")} != ''),
            max(toUInt8({_has_paid_clid_expr()})),
            argMinIf({_first_clid_kind_expr()}, timestamp, {_has_paid_clid_expr()}),
            count(),
            min(timestamp),
            max(timestamp)
        FROM {settings.CLICKHOUSE_DATABASE}.events
        WHERE team_id = %(team_id)s
          AND timestamp >= toDateTime(%(date_start)s)
          AND timestamp < toDateTime(%(date_end)s)
          AND event IN %(included_events)s
        GROUP BY team_id, distinct_id, day
    """
    parameters = {
        "job_id": run.job_id,
        "team_id": config.team_id,
        "date_start": run.date_start,
        "date_end": run.date_end,
        "included_events": tuple(config.included_events),
        "ips_cap": config.ips_per_day_cap,
        "paths_cap": config.paths_per_day_cap,
    }
    cluster.any_host(
        partial(_execute, query=query, parameters=parameters, query_settings=_write_settings(context, run))
    ).result()

    [[rows, devices, empty_ip_rows]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT count(), uniqExact(distinct_id), countIf(empty(ips))
                FROM s3({DEVICE_DAYS.read_args(run)})
            """,
            parameters={},
            query_settings=_read_settings(context, run),
        )
    ).result()
    empty_ip_fraction = (empty_ip_rows / rows) if rows else 0.0
    if rows == 0:
        context.log.warning("Device-day index is empty: no matching events in the window")
    elif empty_ip_fraction > 0.5:
        context.log.warning(
            f"{empty_ip_fraction:.0%} of device-days have no $ip — the team likely has IP "
            "anonymization enabled, so IP-based matching will not work"
        )
    context.add_output_metadata(
        {
            "device_day_rows": dagster.MetadataValue.int(rows),
            "distinct_devices": dagster.MetadataValue.int(devices),
            "empty_ip_fraction": dagster.MetadataValue.float(round(empty_ip_fraction, 4)),
        }
    )
    return run


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        # Iterative with path compression: edge chains can exceed the recursion limit.
        root = self.parent.setdefault(item, item)
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for item in self.parent:
            groups.setdefault(self.find(item), []).append(item)
        return groups


def _fetch_identity_edges(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    run: "MatchingRun",
    *,
    start: str,
    end: str,
    order: str,
) -> list[tuple[str, str, datetime.datetime]]:
    """Deduped (other_id, target_id, first_seen) identity edges with timestamp in [start, end).

    Capped at config.max_identity_edges to bound the in-memory union-find. ``order`` ('ASC' or
    'DESC', a trusted literal — never request input) decides which edges survive truncation:
    anchor edges keep the most recent (DESC, closest to window end), eval edges keep the earliest
    (ASC, each orphan's first post-window merge).
    """
    query = f"""
        SELECT other_id, target_id, min(ts) AS first_seen
        FROM (
            SELECT
                if(event = '$identify', {_prop("$anon_distinct_id")}, {_prop("alias")}) AS other_id,
                distinct_id AS target_id,
                timestamp AS ts
            FROM {settings.CLICKHOUSE_DATABASE}.events
            WHERE team_id = %(team_id)s
              AND event IN %(identity_events)s
              AND timestamp >= toDateTime(%(start)s)
              AND timestamp < toDateTime(%(end)s)
        )
        WHERE other_id != '' AND other_id != target_id
        GROUP BY other_id, target_id
        ORDER BY first_seen {order}, other_id, target_id
        LIMIT %(max_edges)s
    """
    return cluster.any_host(
        partial(
            _execute,
            query=query,
            parameters={
                "team_id": run.config.team_id,
                "identity_events": tuple(IDENTITY_EVENTS),
                "start": start,
                "end": end,
                "max_edges": run.config.max_identity_edges,
            },
            query_settings=_read_settings(context, run),
        )
    ).result()


@dagster.op
def extract_person_timeline(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: MatchingRun,
) -> MatchingRun:
    """Classify distinct_ids as anchors (identified as of window end) and extract evaluation labels.

    The timeline is derived entirely from identity events so it can be evaluated "as of" the
    window end; state tables (person.is_identified, overrides) have no time-travel semantics.
    """
    config = run.config
    # Anchor edges (identity events strictly before window end) classify anchors "as of" window
    # end; eval edges (merges in [date_end, eval_end)) are the ONLY source of training labels.
    # They are fetched as two separate capped queries on purpose: folding both into one query and
    # truncating oldest-first let the high-volume anchor edges silently drop the recent eval edges,
    # which on a large team zeroed out the labels (logreg then skips on 0 positives).
    anchor_edges = _fetch_identity_edges(context, cluster, run, start=run.edges_start, end=run.date_end, order="DESC")
    if len(anchor_edges) >= config.max_identity_edges:
        context.log.warning(
            f"Anchor identity edges truncated at {len(anchor_edges)} (kept the most recent); anchor "
            "classification is incomplete — raise max_identity_edges for full coverage on large teams"
        )
    # Earliest-first so the per-orphan dedup below keeps each orphan's first post-window merge.
    eval_edges = _fetch_identity_edges(context, cluster, run, start=run.date_end, end=run.eval_end, order="ASC")
    if len(eval_edges) >= config.max_identity_edges:
        context.log.warning(f"Eval identity edges truncated at {len(eval_edges)}; some training labels are missing")

    union_find = _UnionFind()
    first_seen_by_id: dict[str, datetime.datetime] = {}
    identified_ids: set[str] = set()
    for other_id, target_id, first_seen in anchor_edges:
        union_find.union(target_id, other_id)
        identified_ids.add(target_id)
        for member in (other_id, target_id):
            if member not in first_seen_by_id or first_seen < first_seen_by_id[member]:
                first_seen_by_id[member] = first_seen

    # The canonical key prefers identified-side ids (merge targets): a bare lexicographic
    # minimum could crown an anonymous device id, which then surfaces as the matched person
    # in the API and UI.
    person_key_by_id: dict[str, str] = {}
    for members in union_find.components().values():
        identified_members = [member for member in members if member in identified_ids]
        person_key = min(identified_members) if identified_members else min(members)
        for member in members:
            person_key_by_id[member] = person_key

    rows: list[tuple[Any, ...]] = [
        (run.job_id, config.team_id, member, 1, person_key, "", "", first_seen_by_id[member])
        for member, person_key in person_key_by_id.items()
    ]
    labeled = 0
    unrecoverable = 0
    seen_eval_orphans: set[str] = set()
    for other_id, target_id, first_seen in eval_edges:
        # An id already identified as of window end is an anchor, not a gradable orphan.
        if other_id in person_key_by_id or other_id in seen_eval_orphans:
            continue
        seen_eval_orphans.add(other_id)
        label_person_key = person_key_by_id.get(target_id, "")
        if label_person_key:
            labeled += 1
        else:
            # The orphan merged into a person that was not an anchor in the window, so no
            # candidate pair could ever have linked it; counted separately in evaluation.
            unrecoverable += 1
        rows.append((run.job_id, config.team_id, other_id, 0, "", label_person_key, target_id, first_seen))

    # Each batch is its own Parquet part object; reads glob `person_timeline/*.parquet`.
    _write_rows_to_s3(context, cluster, PERSON_TIMELINE, run, rows, columns=8)

    anchor_persons = len(set(person_key_by_id.values()))
    context.add_output_metadata(
        {
            "anchor_edges": dagster.MetadataValue.int(len(anchor_edges)),
            "eval_edges": dagster.MetadataValue.int(len(eval_edges)),
            "anchor_distinct_ids": dagster.MetadataValue.int(len(person_key_by_id)),
            "anchor_persons": dagster.MetadataValue.int(anchor_persons),
            "eval_labeled_orphans": dagster.MetadataValue.int(labeled),
            "unrecoverable_eval_orphans": dagster.MetadataValue.int(unrecoverable),
        }
    )
    return run


@dagster.op
def build_candidate_pairs(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: MatchingRun,
) -> MatchingRun:
    """Generate (orphan, anchor person) candidate pairs from IP-day co-location and compute pair features."""
    config = run.config
    query = f"""
        INSERT INTO FUNCTION s3({CANDIDATE_PAIRS.write_args(run, SINGLE_OBJECT)})
        WITH
        anchors AS (
            SELECT distinct_id, person_key
            FROM s3({PERSON_TIMELINE.read_args(run)})
            WHERE is_anchor = 1
        ),
        labels AS (
            SELECT distinct_id, label_person_key
            FROM s3({PERSON_TIMELINE.read_args(run)})
            WHERE is_anchor = 0 AND label_person_key != ''
        ),
        dd AS (
            SELECT *
            FROM s3({DEVICE_DAYS.read_args(run)})
        ),
        ip_day_blocks AS (
            SELECT ip, day, uniqExact(distinct_id) AS block_size
            FROM dd
            ARRAY JOIN ips AS ip
            GROUP BY ip, day
            HAVING block_size <= %(ip_day_block_cap)s
        ),
        ip_window AS (
            SELECT ip
            FROM dd
            ARRAY JOIN ips AS ip
            GROUP BY ip
            HAVING uniqExact(distinct_id) <= %(ip_window_device_cap)s
        ),
        orphan_days AS (
            SELECT
                dd.distinct_id AS distinct_id,
                dd.day AS day,
                ip,
                b.block_size AS block_size,
                dd.geo_city AS geo_city,
                dd.timezone AS timezone,
                dd.browser_language AS browser_language,
                dd.raw_user_agent AS raw_user_agent,
                dd.device_type AS device_type,
                dd.paths AS paths
            FROM dd
            ARRAY JOIN ips AS ip
            INNER JOIN ip_day_blocks AS b USING (ip, day)
            WHERE ip IN (SELECT ip FROM ip_window)
              AND dd.distinct_id NOT IN (SELECT distinct_id FROM anchors)
        ),
        anchor_days AS (
            SELECT
                a.person_key AS person_key,
                dd.day AS day,
                ip,
                dd.geo_city AS geo_city,
                dd.timezone AS timezone,
                dd.browser_language AS browser_language,
                dd.raw_user_agent AS raw_user_agent,
                dd.device_type AS device_type,
                dd.paths AS paths
            FROM dd
            ARRAY JOIN ips AS ip
            INNER JOIN anchors AS a ON dd.distinct_id = a.distinct_id
            WHERE ip IN (SELECT ip FROM ip_window)
        ),
        orphan_totals AS (
            SELECT
                distinct_id,
                min(first_ts) AS o_first,
                max(last_ts) AS o_last,
                sum(event_count) AS o_events,
                max(has_paid_clid) AS o_paid
            FROM dd
            WHERE distinct_id NOT IN (SELECT distinct_id FROM anchors)
            GROUP BY distinct_id
        ),
        anchor_totals AS (
            SELECT
                a.person_key AS person_key,
                min(dd.first_ts) AS a_first,
                max(dd.last_ts) AS a_last,
                sum(dd.event_count) AS a_events,
                max(dd.has_paid_clid) AS a_paid
            FROM dd
            INNER JOIN anchors AS a ON dd.distinct_id = a.distinct_id
            GROUP BY a.person_key
        ),
        pair_core AS (
            SELECT
                o.distinct_id AS orphan_distinct_id,
                a.person_key AS anchor_person_key,
                uniqExact((o.ip, o.day)) AS shared_ip_days,
                uniqExact(o.ip) AS shared_ips,
                min(o.block_size) AS min_ip_block_size,
                max(o.geo_city != '' AND o.geo_city = a.geo_city) AS geo_city_match,
                max(o.timezone != '' AND o.timezone = a.timezone) AS timezone_match,
                max(o.browser_language != '' AND o.browser_language = a.browser_language) AS language_match,
                max(o.raw_user_agent != '' AND o.raw_user_agent = a.raw_user_agent) AS ua_exact_match,
                max(match(o.raw_user_agent, '{WEBVIEW_UA_REGEX}')) AS orphan_is_webview,
                max(
                    (o.device_type = 'Mobile' AND a.device_type = 'Desktop')
                    OR (o.device_type = 'Desktop' AND a.device_type = 'Mobile')
                ) AS device_type_complement,
                uniqExact(o.day) AS days_overlap,
                avg(
                    length(arrayIntersect(o.paths, a.paths))
                    / greatest(length(arrayDistinct(arrayConcat(o.paths, a.paths))), 1)
                ) AS avg_path_jaccard
            FROM orphan_days AS o
            INNER JOIN anchor_days AS a ON o.ip = a.ip AND o.day = a.day
            GROUP BY orphan_distinct_id, anchor_person_key
            ORDER BY orphan_distinct_id, shared_ip_days DESC, shared_ips DESC
            LIMIT %(max_candidates_per_orphan)s BY orphan_distinct_id
        )
        SELECT
            %(job_id)s,
            %(team_id)s,
            p.orphan_distinct_id,
            p.anchor_person_key,
            p.shared_ip_days,
            p.shared_ips,
            p.min_ip_block_size,
            p.geo_city_match,
            p.timezone_match,
            p.language_match,
            p.ua_exact_match,
            p.orphan_is_webview,
            p.device_type_complement,
            p.days_overlap,
            dateDiff('second', o_tot.o_last, a_tot.a_first),
            p.avg_path_jaccard,
            o_tot.o_paid,
            a_tot.a_paid,
            o_tot.o_events,
            a_tot.a_events,
            multiIf(l.distinct_id = '', toInt8(-1), l.label_person_key = p.anchor_person_key, toInt8(1), toInt8(0))
        FROM pair_core AS p
        INNER JOIN orphan_totals AS o_tot ON p.orphan_distinct_id = o_tot.distinct_id
        INNER JOIN anchor_totals AS a_tot ON p.anchor_person_key = a_tot.person_key
        LEFT JOIN labels AS l ON p.orphan_distinct_id = l.distinct_id
    """
    parameters = {
        "job_id": run.job_id,
        "team_id": config.team_id,
        "ip_day_block_cap": config.ip_day_block_cap,
        "ip_window_device_cap": config.ip_window_device_cap,
        "max_candidates_per_orphan": config.max_candidates_per_orphan,
    }
    cluster.any_host(
        partial(_execute, query=query, parameters=parameters, query_settings=_write_settings(context, run))
    ).result()

    [[pair_rows, orphans_with_candidates, positives, negatives]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT count(), uniqExact(orphan_distinct_id), countIf(label = 1), countIf(label = 0)
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
            """,
            parameters={},
            query_settings=_read_settings(context, run),
        )
    ).result()
    context.add_output_metadata(
        {
            "pair_rows": dagster.MetadataValue.int(pair_rows),
            "orphans_with_candidates": dagster.MetadataValue.int(orphans_with_candidates),
            "labeled_positive_pairs": dagster.MetadataValue.int(positives),
            "labeled_negative_pairs": dagster.MetadataValue.int(negatives),
        }
    )
    return run


def _rule_score_expr(weights: dict[str, float]) -> str:
    w = {**DEFAULT_RULE_WEIGHTS, **weights}
    return f"""
        {float(w["shared_ip_day"])} * least(shared_ip_days, 5)
        + {float(w["multi_ip"])} * (shared_ips >= 2)
        + {float(w["small_block"])} * (min_ip_block_size <= 3)
        + {float(w["geo_city"])} * geo_city_match
        + {float(w["timezone"])} * timezone_match
        + {float(w["language"])} * language_match
        + {float(w["ua_exact"])} * ua_exact_match
        + {float(w["webview_same_ua"])} * (orphan_is_webview AND ua_exact_match)
        + {float(w["device_complement"])} * device_type_complement
        + {float(w["path_jaccard"])} * avg_path_jaccard
        + {float(w["paid_continuity"])} * (orphan_paid_touch AND NOT anchor_paid_touch)
    """


@dagster.op
def score_rule_based(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: MatchingRun,
) -> MatchingRun:
    """Score candidate pairs with the weighted rules and keep the best anchor per orphan."""
    config = run.config
    query = f"""
        INSERT INTO FUNCTION s3({LINKS.write_args(run, f"{RULES_MODEL_VERSION}.parquet")})
        SELECT
            %(job_id)s,
            %(team_id)s,
            '{RULES_MODEL_VERSION}',
            orphan_distinct_id,
            anchor_person_key,
            score,
            runner_up,
            score - runner_up,
            multiIf(score >= %(tier_high)s, 'high', score >= %(tier_medium)s, 'medium', 'low'),
            now()
        FROM (
            SELECT
                orphan_distinct_id,
                anchor_person_key,
                score,
                row_number() OVER (
                    PARTITION BY orphan_distinct_id ORDER BY score DESC, anchor_person_key
                ) AS rn,
                leadInFrame(score) OVER (
                    PARTITION BY orphan_distinct_id ORDER BY score DESC, anchor_person_key
                    ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
                ) AS runner_up
            FROM (
                SELECT
                    orphan_distinct_id,
                    anchor_person_key,
                    ({_rule_score_expr(config.rule_weights)}) AS score
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
            )
        )
        WHERE rn = 1 AND score >= %(min_score)s AND (score - runner_up) >= %(min_margin)s
    """
    parameters = {
        "job_id": run.job_id,
        "team_id": config.team_id,
        "tier_high": config.rule_tier_high,
        "tier_medium": config.rule_tier_medium,
        "min_score": config.rule_min_score,
        "min_margin": config.rule_min_margin,
    }
    cluster.any_host(
        partial(_execute, query=query, parameters=parameters, query_settings=_write_settings(context, run))
    ).result()

    [[links]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT count()
                FROM s3({LINKS.read_args(run)})
                WHERE model_version = '{RULES_MODEL_VERSION}'
            """,
            parameters={},
            query_settings=_read_settings(context, run),
        )
    ).result()
    context.add_output_metadata({"rule_links": dagster.MetadataValue.int(links)})
    return run


def _deterministic_test_split(key: str, modulo: int = 5) -> bool:
    """Stable orphan-level holdout assignment so an orphan's pairs never straddle train/test."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % modulo == 0


@dagster.op
def train_logreg_and_score(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: MatchingRun,
) -> MatchingRun:
    """Train a logistic regression on merge-derived labels and score all candidate pairs.

    Skips gracefully (no links inserted) when there are too few labels to train, so the job
    stays usable on small teams and in local development.
    """
    # numpy/sklearn are deferred to keep the heavy dependency off the Dagster code-location
    # import path; this op is the only consumer.
    import numpy as np  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415
    from sklearn.pipeline import make_pipeline  # noqa: PLC0415
    from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

    config = run.config
    feature_cols = ", ".join(PAIR_FEATURE_COLUMNS)
    labeled_rows: list[tuple[Any, ...]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT orphan_distinct_id, label, {feature_cols}
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
                WHERE label != -1
                LIMIT %(max_rows)s
            """,
            parameters={"max_rows": config.max_training_rows},
            query_settings=_read_settings(context, run),
        )
    ).result()
    positives = sum(1 for row in labeled_rows if row[1] == 1)
    negatives = len(labeled_rows) - positives
    if positives < config.min_training_positives or negatives < config.min_training_negatives:
        context.log.warning(
            f"Skipping logistic regression: {positives} positives / {negatives} negatives, "
            f"need at least {config.min_training_positives} / {config.min_training_negatives}"
        )
        context.add_output_metadata(
            {
                "trained": dagster.MetadataValue.bool(False),
                "labeled_positives": dagster.MetadataValue.int(positives),
                "labeled_negatives": dagster.MetadataValue.int(negatives),
            }
        )
        return run

    weak_negative_count = int(config.weak_negative_sample_ratio * len(labeled_rows))
    weak_rows: list[tuple[Any, ...]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT orphan_distinct_id, label, {feature_cols}
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
                WHERE label = -1
                ORDER BY cityHash64(orphan_distinct_id, anchor_person_key)
                LIMIT %(limit)s
            """,
            parameters={"limit": weak_negative_count},
            query_settings=_read_settings(context, run),
        )
    ).result()

    train_x: list[Sequence[float]] = []
    train_y: list[int] = []
    train_weights: list[float] = []
    test_x: list[Sequence[float]] = []
    test_y: list[int] = []
    for orphan_id, label, *features in labeled_rows:
        if _deterministic_test_split(orphan_id):
            test_x.append(features)
            test_y.append(label)
        else:
            train_x.append(features)
            train_y.append(label)
            train_weights.append(1.0)
    # Unlabeled pairs are weak negatives: the absence of a later merge does not prove the
    # link is wrong, so they get a reduced sample weight and never enter the holdout.
    for _orphan_id, _label, *features in weak_rows:
        train_x.append(features)
        train_y.append(0)
        train_weights.append(0.3)

    if len(set(train_y)) < 2:
        context.log.warning("Skipping logistic regression: training data has a single class")
        context.add_output_metadata({"trained": dagster.MetadataValue.bool(False)})
        return run

    model = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
    model.fit(np.array(train_x, dtype=np.float64), np.array(train_y), logisticregression__sample_weight=train_weights)

    coefficients = dict(
        zip(PAIR_FEATURE_COLUMNS, model.named_steps["logisticregression"].coef_[0].round(4).tolist(), strict=True)
    )
    metadata: dict[str, Any] = {
        "trained": dagster.MetadataValue.bool(True),
        "labeled_positives": dagster.MetadataValue.int(positives),
        "labeled_negatives": dagster.MetadataValue.int(negatives),
        "weak_negatives": dagster.MetadataValue.int(len(weak_rows)),
        "coefficients": dagster.MetadataValue.json(coefficients),
    }
    if test_x and len(set(test_y)) == 2:
        test_probs = model.predict_proba(np.array(test_x, dtype=np.float64))[:, 1]
        metadata["holdout_rows"] = dagster.MetadataValue.int(len(test_y))
        metadata["holdout_auc"] = dagster.MetadataValue.float(round(float(roc_auc_score(test_y, test_probs)), 4))
    else:
        context.log.warning("Holdout slice lacks both classes; skipping holdout metrics")

    scoring_rows: list[tuple[Any, ...]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT orphan_distinct_id, anchor_person_key, {feature_cols}
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
                ORDER BY orphan_distinct_id, anchor_person_key
                LIMIT %(max_rows)s
            """,
            parameters={"max_rows": config.max_scoring_rows},
            query_settings=_read_settings(context, run),
        )
    ).result()
    if len(scoring_rows) >= config.max_scoring_rows:
        context.log.warning(f"Candidate pairs truncated at {len(scoring_rows)} for scoring")

    link_rows: list[tuple[Any, ...]] = []
    if scoring_rows:
        probs = model.predict_proba(np.array([row[2:] for row in scoring_rows], dtype=np.float64))[:, 1]
        best_by_orphan: dict[str, tuple[float, str, float]] = {}
        for (orphan_id, anchor_key, *_features), prob in zip(scoring_rows, probs, strict=True):
            prob = float(prob)
            best = best_by_orphan.get(orphan_id)
            if best is None:
                best_by_orphan[orphan_id] = (prob, anchor_key, 0.0)
            elif prob > best[0]:
                best_by_orphan[orphan_id] = (prob, anchor_key, best[0])
            elif prob > best[2]:
                best_by_orphan[orphan_id] = (best[0], best[1], prob)
        computed_at = datetime.datetime.now(datetime.UTC)
        for orphan_id, (prob, anchor_key, runner_up) in best_by_orphan.items():
            # Mirror the rule model's min-score / min-margin gate so logreg emits confident links
            # instead of one row per orphan-with-candidates regardless of predicted probability.
            if prob < config.logreg_min_prob or (prob - runner_up) < config.logreg_min_margin:
                continue
            tier = "high" if prob >= config.prob_tier_high else "medium" if prob >= config.prob_tier_medium else "low"
            link_rows.append(
                (
                    run.job_id,
                    config.team_id,
                    LOGREG_MODEL_VERSION,
                    orphan_id,
                    anchor_key,
                    prob,
                    runner_up,
                    prob - runner_up,
                    tier,
                    computed_at,
                )
            )

    # Winners go to their own `links/logreg_v1_part_<n>.parquet` objects (the rules op already
    # wrote `links/rules_v1.parquet`); the read side unions them with `links/*.parquet`.
    _write_rows_to_s3(
        context, cluster, LINKS, run, link_rows, columns=10, filename_prefix=f"{LOGREG_MODEL_VERSION}_part"
    )

    metadata["logreg_links"] = dagster.MetadataValue.int(len(link_rows))
    context.add_output_metadata(metadata)
    return run


def _post_run_report_to_slack(
    context: dagster.OpExecutionContext,
    slack: dagster_slack.SlackResource,
    run: "MatchingRun",
    *,
    channel: str,
    report: str,
    devices: int,
    orphan_devices: int,
    anchor_devices: int,
    orphans_with_candidates: int,
    gradable_orphans: int,
    unrecoverable_orphans: int,
    model_headlines: list[str],
) -> None:
    """Post a readable success summary to Slack with the full report attached.

    Only runs on Cloud deployments (the Slack resource is a no-op locally) and never fails the
    op: the report is already logged and in op metadata, so a Slack outage must not lose a run.
    """
    if not settings.CLOUD_DEPLOYMENT:
        context.log.info("Skipping Slack report in non-prod environment")
        return
    if not channel:
        context.log.info("Skipping Slack report: no slack_channel configured")
        return

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "✅ Identity matching run complete", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Env *{settings.CLOUD_DEPLOYMENT}* • team `{run.config.team_id}` • "
                    f"window `[{run.date_start}, {run.date_end})` • eval until `{run.eval_end}`",
                }
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"job_id `{run.job_id}`"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Coverage*\n"
                    f"• Active devices: *{devices:,}*  ({orphan_devices:,} orphan / {anchor_devices:,} anchor)\n"
                    f"• Orphans with ≥1 candidate: *{orphans_with_candidates:,}*\n"
                    f"• Gradable labeled orphans: *{gradable_orphans:,}*  (+{unrecoverable_orphans:,} unrecoverable)"
                ),
            },
        },
    ]
    if model_headlines:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Models*\n" + "\n".join(f"• {line}" for line in model_headlines)},
            }
        )

    try:
        client = slack.get_client()
        # text= is the notification/fallback for clients that don't render blocks.
        response = client.chat_postMessage(channel=channel, blocks=blocks, text="Identity matching run complete")
        # files_upload_v2 needs the channel ID, which chat_postMessage returns.
        client.files_upload_v2(
            channel=response.get("channel"),
            content=report,
            filename=f"identity_matching_{run.job_id}.md",
            title="Identity matching report",
            initial_comment="Full evaluation report attached.",
        )
    except Exception:
        context.log.exception("Failed to post identity matching report to Slack")


@dagster.op
def evaluate_and_report(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    slack: dagster.ResourceParam[dagster_slack.SlackResource],
    rules_run: MatchingRun,
    logreg_run: MatchingRun,
) -> None:
    """Grade links against held-out merge labels and report coverage and marketing impact."""
    if rules_run.job_id != logreg_run.job_id:
        raise ValueError(f"Mismatched runs: {rules_run.job_id!r} vs {logreg_run.job_id!r}")
    run = rules_run
    config = run.config
    ch_settings = _read_settings(context, run)

    [[devices, anchor_devices]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT uniqExact(d.distinct_id), uniqExactIf(d.distinct_id, t.is_anchor = 1)
                FROM s3({DEVICE_DAYS.read_args(run)}) AS d
                LEFT JOIN (
                    SELECT distinct_id, is_anchor
                    FROM s3({PERSON_TIMELINE.read_args(run)})
                ) AS t ON d.distinct_id = t.distinct_id
            """,
            parameters={},
            query_settings=ch_settings,
        )
    ).result()
    orphan_devices = devices - anchor_devices

    [[gradable_orphans, unrecoverable_orphans]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT
                    uniqExactIf(t.distinct_id, t.label_person_key != ''),
                    uniqExactIf(t.distinct_id, t.label_person_key = '')
                FROM s3({PERSON_TIMELINE.read_args(run)}) AS t
                INNER JOIN (
                    SELECT DISTINCT distinct_id
                    FROM s3({DEVICE_DAYS.read_args(run)})
                ) AS d ON t.distinct_id = d.distinct_id
                WHERE t.is_anchor = 0
            """,
            parameters={},
            query_settings=ch_settings,
        )
    ).result()

    [[orphans_with_candidates]] = cluster.any_host(
        partial(
            _execute,
            query=f"""
                SELECT uniqExact(orphan_distinct_id)
                FROM s3({CANDIDATE_PAIRS.read_args(run)})
            """,
            parameters={},
            query_settings=ch_settings,
        )
    ).result()

    summary_lines = [
        f"Window [{run.date_start}, {run.date_end}), eval horizon until {run.eval_end}",
        f"Orphan devices: {orphan_devices} (of {devices} active devices; {anchor_devices} anchor devices)",
        f"Orphans with at least one candidate: {orphans_with_candidates}",
        f"Gradable labeled orphans (active in window): {gradable_orphans}",
        f"Unrecoverable labeled orphans (merge target not an anchor in window): {unrecoverable_orphans}",
    ]

    metadata: dict[str, Any] = {
        "orphan_devices": dagster.MetadataValue.int(orphan_devices),
        "orphans_with_candidates": dagster.MetadataValue.int(orphans_with_candidates),
        "gradable_orphans": dagster.MetadataValue.int(gradable_orphans),
        "unrecoverable_orphans": dagster.MetadataValue.int(unrecoverable_orphans),
    }

    sweeps = {
        RULES_MODEL_VERSION: [float(t) for t in config.rule_thresholds],
        LOGREG_MODEL_VERSION: [float(t) for t in config.prob_thresholds],
    }
    model_headlines: list[str] = []  # one readable line per model for the Slack summary
    for model_version, thresholds in sweeps.items():
        link_rows: list[tuple[float, str, str, int, int]] = cluster.any_host(
            partial(
                _execute,
                query=f"""
                    SELECT
                        lk.score,
                        lk.anchor_person_key,
                        t.label_person_key,
                        p.orphan_paid_touch,
                        p.anchor_paid_touch
                    FROM s3({LINKS.read_args(run)}) AS lk
                    INNER JOIN s3({CANDIDATE_PAIRS.read_args(run)}) AS p
                        ON lk.orphan_distinct_id = p.orphan_distinct_id
                        AND lk.anchor_person_key = p.anchor_person_key
                    LEFT JOIN (
                        SELECT distinct_id, label_person_key
                        FROM s3({PERSON_TIMELINE.read_args(run)})
                        WHERE is_anchor = 0 AND label_person_key != ''
                    ) AS t ON lk.orphan_distinct_id = t.distinct_id
                    WHERE lk.model_version = %(model_version)s
                """,
                parameters={"model_version": model_version},
                query_settings=ch_settings,
            )
        ).result()

        if not link_rows:
            note = ""
            if model_version == LOGREG_MODEL_VERSION:
                # logreg writes no links when it skips training; surface the likely reason rather
                # than a bare "no links" (see the label-count gate in train_logreg_and_score).
                note = (
                    f" — logreg needs ≥{config.min_training_positives} positive / "
                    f"≥{config.min_training_negatives} negative labels; this run had {gradable_orphans} "
                    f"gradable labeled orphans. If that is ~0, the eval horizon has not elapsed "
                    f"(eval until {run.eval_end}) or identity edges were truncated."
                )
            summary_lines.append(f"\n{model_version}: no links{note}")
            model_headlines.append(f"*{model_version}*: no links{note}")
            continue

        table_lines = [
            f"\n{model_version} ({len(link_rows)} links):",
            "| threshold | links | graded | precision | recall | new paid touches |",
            "|---|---|---|---|---|---|",
        ]
        best: tuple[float, float, float, int] | None = None  # (precision, threshold, recall, links)
        for threshold in thresholds:
            at_t = [row for row in link_rows if row[0] >= threshold]
            graded = [row for row in at_t if row[2] != ""]
            correct = sum(1 for row in graded if row[1] == row[2])
            precision = (correct / len(graded)) if graded else None
            recall = (correct / gradable_orphans) if gradable_orphans else None
            paid_gain = sum(1 for row in at_t if row[3] == 1 and row[4] == 0)
            if precision is not None and (best is None or precision > best[0]):
                best = (precision, threshold, recall or 0.0, len(at_t))
            table_lines.append(
                f"| {threshold} | {len(at_t)} | {len(graded)} "
                f"| {f'{precision:.3f}' if precision is not None else 'n/a'} "
                f"| {f'{recall:.3f}' if recall is not None else 'n/a'} "
                f"| {paid_gain} |"
            )
        summary_lines.extend(table_lines)
        metadata[f"{model_version}_sweep"] = dagster.MetadataValue.md("\n".join(table_lines))
        if best is not None:
            model_headlines.append(
                f"*{model_version}*: {len(link_rows)} links · best precision {best[0]:.3f} "
                f"at score ≥{best[1]} ({best[3]} links, recall {best[2]:.3f})"
            )
        else:
            model_headlines.append(f"*{model_version}*: {len(link_rows)} links (no graded labels)")

    report = "\n".join(summary_lines)
    context.log.info("Identity matching report:\n%s", report)
    context.add_output_metadata({**metadata, "report": dagster.MetadataValue.md(report)})
    _post_run_report_to_slack(
        context,
        slack,
        run,
        channel=config.slack_channel,
        report=report,
        devices=devices,
        orphan_devices=orphan_devices,
        anchor_devices=anchor_devices,
        orphans_with_candidates=orphans_with_candidates,
        gradable_orphans=gradable_orphans,
        unrecoverable_orphans=unrecoverable_orphans,
        model_headlines=model_headlines,
    )


def _execute(
    client: Client,
    query: str,
    parameters: dict[str, Any] | list[tuple[Any, ...]] | None = None,
    query_settings: dict[str, str] | None = None,
) -> list[tuple[Any, ...]]:
    return client.execute(query, parameters, settings=query_settings)


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def identity_matching_job():
    run = prepare_run()
    run = build_device_day_index(run)
    run = extract_person_timeline(run)
    run = build_candidate_pairs(run)
    rules = score_rule_based(run)
    logreg = train_logreg_and_score(run)
    evaluate_and_report(rules, logreg)
