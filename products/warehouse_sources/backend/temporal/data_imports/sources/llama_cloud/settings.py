from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# LlamaCloud API keys are region-specific: a key minted in one region only works
# against that region's host (https://developers.llamaindex.ai/python/cloud/general/regions).
LLAMA_CLOUD_REGIONS: dict[str, str] = {
    "na": "https://api.cloud.llamaindex.ai",
    "eu": "https://api.cloud.eu.llamaindex.ai",
}
DEFAULT_LLAMA_CLOUD_REGION = "na"

# The classify listing caps page_size at 100; the other cursor endpoints don't document a
# maximum, so 100 is safe everywhere.
DEFAULT_PAGE_SIZE = 100

# Jobs commonly transition status (PENDING -> COMPLETED/FAILED) shortly after creation, but
# the API only filters on created_at — so each incremental run re-reads a trailing day of
# rows to pick up those transitions; merge dedupes them on the primary key.
JOB_STATUS_LOOKBACK_SECONDS = 24 * 60 * 60

CREATED_AT_INCREMENTAL: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

DAY_INCREMENTAL: IncrementalField = {
    "label": "day",
    "type": IncrementalFieldType.Date,
    "field": "day",
    "field_type": IncrementalFieldType.Date,
}

JOB_ENDPOINT_DESCRIPTION = (
    "Incremental syncs filter on created_at, re-reading a trailing 24h window so recent status "
    "transitions are picked up; status changes to jobs created earlier than that are only "
    "reflected on a full refresh"
)


@dataclass
class LlamaCloudEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side inclusive lower-bound query param backing incremental syncs
    # (None -> the endpoint has no timestamp filter, full refresh only).
    incremental_param: str | None = None
    partition_key: str | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = DEFAULT_PAGE_SIZE
    # False for endpoints that return a bare JSON array with no page_token support.
    paginated: bool = True
    # /api/v1/beta/usage-metrics requires organization_id; it's resolved at sync time
    # from the key's project (see _resolve_organization_id).
    requires_organization_id: bool = False
    description: str | None = None
    default_incremental_lookback_seconds: int | None = None
    # Allowlist of top-level fields to keep per row. Set for config-style endpoints whose
    # payloads embed third-party credentials in nested config objects — projecting onto the
    # documented, non-sensitive fields keeps secrets out of the warehouse. None imports every field.
    output_fields: frozenset[str] | None = None
    # Whether raw HTTP responses may be captured as anonymized samples. Off for endpoints
    # whose responses carry secrets the name-based sample scrubbers can't fully catch.
    capture_http_samples: bool = True


LLAMA_CLOUD_ENDPOINTS: dict[str, LlamaCloudEndpointConfig] = {
    "parse_jobs": LlamaCloudEndpointConfig(
        name="parse_jobs",
        path="/api/v2/parse",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
    ),
    "extract_jobs": LlamaCloudEndpointConfig(
        name="extract_jobs",
        path="/api/v2/extract",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
    ),
    "classify_jobs": LlamaCloudEndpointConfig(
        name="classify_jobs",
        path="/api/v2/classify",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
    ),
    "batches": LlamaCloudEndpointConfig(
        name="batches",
        path="/api/v2/batches",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
    ),
    "split_jobs": LlamaCloudEndpointConfig(
        name="split_jobs",
        path="/api/v1/split/jobs",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
    ),
    "sheets_jobs": LlamaCloudEndpointConfig(
        name="sheets_jobs",
        path="/api/v1/sheets/jobs",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        incremental_param="created_at_on_or_after",
        partition_key="created_at",
        description=JOB_ENDPOINT_DESCRIPTION,
        default_incremental_lookback_seconds=JOB_STATUS_LOOKBACK_SECONDS,
        # Sheets jobs embed webhook credentials (signing secrets, auth headers) under nested
        # `parameters.webhook_configurations`, so import only the documented job metadata
        # (matches canonical_descriptions) and skip sampling.
        output_fields=frozenset(
            {
                "id",
                "created_at",
                "updated_at",
                "project_id",
                "user_id",
                "status",
                "success",
                "file_id",
                "regions",
                "worksheet_metadata",
                "errors",
            }
        ),
        capture_http_samples=False,
    ),
    "projects": LlamaCloudEndpointConfig(
        name="projects",
        path="/api/v2/projects",
        # The projects listing has no timestamp filter, so full refresh only.
    ),
    "pipelines": LlamaCloudEndpointConfig(
        name="pipelines",
        path="/api/v1/pipelines",
        # Returns a bare JSON array with neither pagination nor timestamp filters.
        paginated=False,
        # Pipeline definitions embed nested embedding-provider and data-sink credentials, so
        # import only the documented metadata (matches canonical_descriptions) and skip sampling.
        output_fields=frozenset({"id", "created_at", "updated_at", "name", "project_id", "pipeline_type"}),
        capture_http_samples=False,
    ),
    "files": LlamaCloudEndpointConfig(
        name="files",
        path="/api/v1/beta/files",
        # The files listing has no timestamp filter (last_modified_at is not filterable),
        # so full refresh only.
        # Each file row carries a presigned `download_url` (and form fields) granting access to
        # the private source document, so import only the documented metadata (matches
        # canonical_descriptions) and skip sampling.
        output_fields=frozenset(
            {
                "id",
                "name",
                "external_file_id",
                "file_type",
                "project_id",
                "last_modified_at",
                "expires_at",
                "purpose",
            }
        ),
        capture_http_samples=False,
    ),
    "usage_metrics": LlamaCloudEndpointConfig(
        name="usage_metrics",
        path="/api/v1/beta/usage-metrics",
        incremental_fields=[DAY_INCREMENTAL],
        incremental_param="day_on_or_after",
        requires_organization_id=True,
        # `day_on_or_after` is inclusive, so the boundary day is re-read each run and its
        # still-accumulating totals are updated via merge on the primary key.
        description="Per-day usage and credit consumption aggregates",
    ),
}

ENDPOINTS = tuple(LLAMA_CLOUD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LLAMA_CLOUD_ENDPOINTS.items()
}
