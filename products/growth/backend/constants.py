from typing import Literal, TypedDict

from django.conf import settings

SDK_CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days — used by the GitHub `latestVersion` cache (hourly Dagster job)

# Team-events snapshot TTL — sized to self-heal one missed daily cron run.
# The Temporal `sdk_outdated` cron starts at 08:00 UTC; per-team writes happen mid-batch, so the
# previous day's write for any given team can be timestamped meaningfully later. A 26h TTL gives
# ~2h headroom relative to cron *start*, and less for teams late in the batch queue. That's
# deliberate: when a team's TTL expires before its next batch slot, the next user request hits
# the cache-miss fallback in posthog/api/sdk_health.py:get_team_data, which runs one fresh
# single-team HogQL query and repopulates Redis. Steady-state load is unchanged; the trade-off
# prevents days-long stale snapshots when a team's batch is skipped or times out.
TEAM_SDK_CACHE_EXPIRY = 60 * 60 * 26  # 26 hours


# Canonical list of the SDK identifiers SDK Health tracks. Lives here (rather than in
# products/growth/dags/github_sdk_versions.py) so non-Dagster consumers — the Temporal
# health check, the API view, and tests — don't need to import from a Dagster module.
SdkTypes = Literal[
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]
SDK_TYPES: list[SdkTypes] = [
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]


class SdkVersionEntry(TypedDict):
    lib_version: str
    max_timestamp: str
    count: int


# Identity matching no longer persists tables on the ClickHouse cluster. Each run of
# products/growth/dags/identity_matching.py writes its datasets as Parquet to a pre-provisioned
# ClickHouse "scratch" S3 bucket, namespaced per team and run:
#
#   <prefix>/team_<team_id>/<job_id>/device_days/data.parquet
#   <prefix>/team_<team_id>/<job_id>/person_timeline/part_<n>.parquet
#   <prefix>/team_<team_id>/<job_id>/candidate_pairs/data.parquet
#   <prefix>/team_<team_id>/<job_id>/links/rules_v1.parquet
#   <prefix>/team_<team_id>/<job_id>/links/logreg_v1_part_<n>.parquet
#
# The job_id segment gives per-run isolation; the team_<team_id> segment lets the read API
# enumerate a team's runs with a glob without reading other teams' objects. All S3 I/O is
# mediated by ClickHouse (`INSERT INTO FUNCTION s3` / `FROM s3`); the dataset path-segment
# constants, Parquet schemas, and the `s3(...)` argument builder live here (not in the Dagster
# module) so the read API can build identical URLs without importing Dagster.
IDENTITY_MATCHING_DEVICE_DAYS_DATASET = "device_days"
IDENTITY_MATCHING_PERSON_TIMELINE_DATASET = "person_timeline"
IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET = "candidate_pairs"
IDENTITY_MATCHING_LINKS_DATASET = "links"

IDENTITY_MATCHING_RULES_MODEL_VERSION = "rules_v1"
IDENTITY_MATCHING_LOGREG_MODEL_VERSION = "logreg_v1"
IDENTITY_MATCHING_TIERS = ["high", "medium", "low"]

# Person properties surfaced per link so a reviewer can sanity-check a match at a glance: identity
# (email/name) plus the dimensions the models score on — geo, device, and campaign attribution.
# Maps raw person-property keys to clean API field names (the `$`-prefixed keys can't be serializer
# field names). Kept curated rather than dumping every property: the payload stays bounded, and the
# chosen fields mirror the match signals so "same city? same browser? same campaign?" is one glance.
IDENTITY_MATCHING_PERSON_PROPERTY_MAP: dict[str, str] = {
    "email": "email",
    "name": "name",
    "$geoip_city_name": "city",
    "$geoip_country_code": "country",
    "$browser": "browser",
    "$os": "os",
    "$device_type": "device_type",
    "$timezone": "timezone",
    "$initial_utm_source": "utm_source",
    "$initial_utm_medium": "utm_medium",
    "$initial_utm_campaign": "utm_campaign",
    "$initial_referring_domain": "referring_domain",
    "$initial_gclid": "gclid",
}

# Parquet column schemas, passed as the explicit `structure` argument to `s3(...)`. They are
# *required* for the VALUES-based writes (person_timeline, logreg links) and used on every read
# so that a glob matching no objects returns zero rows instead of failing schema inference (the
# "no run yet" path). `job_id` is `String` because ClickHouse cannot write `UUID` to Parquet;
# `model_version`/`tier` are plain `String` because `LowCardinality` is a MergeTree-only
# optimisation. On writes the structure also drives ClickHouse's cast of the projection, exactly
# as the old `INSERT INTO <table>` did against the column types — so the column order here must
# match each op's SELECT/VALUES projection order.
IDENTITY_MATCHING_DEVICE_DAYS_STRUCTURE = """
    job_id String,
    team_id Int64,
    distinct_id String,
    day Date,
    ips Array(String),
    browser String,
    os String,
    device_type String,
    timezone String,
    browser_language String,
    raw_user_agent String,
    geo_city String,
    geo_subdivision String,
    geo_postal String,
    paths Array(String),
    referring_domain String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    has_paid_clid UInt8,
    first_clid_kind String,
    event_count UInt64,
    first_ts DateTime64(6, 'UTC'),
    last_ts DateTime64(6, 'UTC')
"""

IDENTITY_MATCHING_PERSON_TIMELINE_STRUCTURE = """
    job_id String,
    team_id Int64,
    distinct_id String,
    is_anchor UInt8,
    person_key String,
    label_person_key String,
    label_target_id String,
    first_seen DateTime64(6, 'UTC')
"""

IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE = """
    job_id String,
    team_id Int64,
    orphan_distinct_id String,
    anchor_person_key String,
    shared_ip_days UInt32,
    shared_ips UInt32,
    min_ip_block_size UInt32,
    geo_city_match UInt8,
    timezone_match UInt8,
    language_match UInt8,
    ua_exact_match UInt8,
    orphan_is_webview UInt8,
    device_type_complement UInt8,
    days_overlap UInt32,
    orphan_last_to_anchor_first_s Int64,
    avg_path_jaccard Float32,
    orphan_paid_touch UInt8,
    anchor_paid_touch UInt8,
    orphan_event_count UInt64,
    anchor_event_count UInt64,
    label Int8
"""

IDENTITY_MATCHING_LINKS_STRUCTURE = """
    job_id String,
    team_id Int64,
    model_version String,
    orphan_distinct_id String,
    anchor_person_key String,
    score Float64,
    runner_up_score Float64,
    margin Float64,
    tier String,
    computed_at DateTime
"""


# On a Cloud deployment the scratch bucket must be a dedicated, infra-provided bucket distinct
# from the general object-storage bucket. IDENTITY_MATCHING_S3_BUCKET falls back to
# OBJECT_STORAGE_BUCKET when its env var is unset, so equality on Cloud means the var is missing
# and every s3() call would target the wrong bucket (the app-assets bucket the ClickHouse role
# cannot access) — a silent AccessDenied. Both the Dagster job and the read API check this so a
# missing env on either deployment fails loudly instead of 500-ing on AccessDenied.
IDENTITY_MATCHING_S3_UNCONFIGURED_MESSAGE = (
    "IDENTITY_MATCHING_S3_BUCKET is not set on this deployment, so identity matching falls back to "
    "the general object-storage bucket, which the ClickHouse role cannot access. Set it to the "
    "scratch bucket (the same value as the Dagster deployment) on every deployment that runs the "
    "identity matching job or its read API."
)


def identity_matching_s3_unconfigured() -> bool:
    """True when the scratch bucket isn't configured on a Cloud deployment (see message above)."""
    return bool(settings.CLOUD_DEPLOYMENT) and settings.IDENTITY_MATCHING_S3_BUCKET == settings.OBJECT_STORAGE_BUCKET


def identity_matching_run_prefix(team_id: int, job_id: str) -> str:
    """S3 key prefix for one run: `<prefix>/team_<team_id>/<job_id>`.

    `job_id` is either a run UUID (string) or the glob `*` to enumerate every run of a team.
    """
    return f"{settings.IDENTITY_MATCHING_S3_PREFIX}/team_{team_id}/{job_id}"


def identity_matching_s3_args(team_id: int, job_id: str, relative_path: str, structure: str) -> str:
    """Build the argument list for a ClickHouse `s3(...)` call: ``url[, key, secret], 'Parquet', structure``.

    Credentials are emitted only when an endpoint is configured (local/dev/test object storage);
    on prod the endpoint is empty and the cluster reaches the bucket via its attached IAM role, so
    no secret is ever interpolated into SQL. ``team_id`` (int), ``job_id`` (run UUID or ``*``) and
    ``relative_path`` (constant dataset segments) are all trusted, never request input.
    """
    key = f"{identity_matching_run_prefix(team_id, job_id)}/{relative_path}"
    endpoint = settings.IDENTITY_MATCHING_S3_ENDPOINT
    if endpoint:
        # Local/dev/test S3-compatible storage (SeaweedFS/MinIO): path-style URL including bucket.
        url = f"{endpoint}/{settings.IDENTITY_MATCHING_S3_BUCKET}/{key}"
        creds = f"'{settings.OBJECT_STORAGE_ACCESS_KEY_ID}', '{settings.OBJECT_STORAGE_SECRET_ACCESS_KEY}', "
    else:
        # Prod AWS S3: virtual-hosted-style HTTPS URL; the cluster authenticates via its IAM role.
        url = f"https://{settings.IDENTITY_MATCHING_S3_BUCKET}.s3.{settings.IDENTITY_MATCHING_S3_REGION}.amazonaws.com/{key}"
        creds = ""
    # The structure is wrapped in a single-quoted SQL literal, so escape the single quotes inside
    # column types like DateTime64(6, 'UTC') — otherwise they terminate the literal early.
    compact_structure = " ".join(structure.split()).replace("'", "\\'")
    return f"'{url}', {creds}'Parquet', '{compact_structure}'"


def identity_matching_dataset_read_args(team_id: int, job_id: str, dataset: str, structure: str) -> str:
    """`s3(...)` args reading every Parquet part of a dataset under a run (or all runs when job_id=``*``)."""
    return identity_matching_s3_args(team_id, job_id, f"{dataset}/*.parquet", structure)


def github_sdk_versions_key(sdk_type: str) -> str:
    return f"github:sdk_versions:{sdk_type}"


def team_sdk_versions_key(team_id: int) -> str:
    return f"sdk_versions:team:{team_id}"
