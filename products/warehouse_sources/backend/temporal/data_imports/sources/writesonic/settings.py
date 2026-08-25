from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.writesonic.com"

# Writesonic caps `size` at 100 per page (default 50).
PAGE_SIZE = 100

# The performance/content export endpoints require a `date` param (one UTC day per request), so a
# first sync walks day windows backwards-bounded by this lookback. GEO tracking only produces data
# from the day a site was onboarded, so earlier days simply return empty pages.
DEFAULT_LOOKBACK_DAYS = 365


@dataclass
class WritesonicEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Daily endpoints require a `date` query param (UTC day) and are synced one day at a time,
    # which is also the incremental granularity. Non-daily (config) endpoints are full refresh.
    daily: bool = False
    # The content export rows don't carry the requested export date, so we stamp it in — it's
    # both part of the primary key and the incremental/partition field.
    inject_date: bool = False
    # Stable field used for datetime partitioning. Must never change after a row is written.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


_DATE_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


WRITESONIC_ENDPOINTS: dict[str, WritesonicEndpointConfig] = {
    # Daily aggregated KPIs (visibility score, rank, mentions) per tracked website.
    "performance_summary": WritesonicEndpointConfig(
        name="performance_summary",
        path="/v2/geo/presence/business/export/performance/summary",
        primary_keys=["date", "website_id"],
        daily=True,
        partition_key="date",
        incremental_fields=[_DATE_FIELD],
    ),
    # Aggregated performance per prompt (across AI platforms) for the given day.
    "performance_prompts": WritesonicEndpointConfig(
        name="performance_prompts",
        path="/v2/geo/presence/business/export/performance/prompts",
        primary_keys=["date", "prompt_id"],
        daily=True,
        partition_key="date",
        incremental_fields=[_DATE_FIELD],
    ),
    # Raw response-level rows with brand mentions per prompt-topic-platform for the given day.
    # `response_id`'s uniqueness scope isn't documented, so the date stays in the key.
    "performance_answers": WritesonicEndpointConfig(
        name="performance_answers",
        path="/v2/geo/presence/business/export/performance/answers",
        primary_keys=["date", "response_id"],
        daily=True,
        partition_key="date",
        incremental_fields=[_DATE_FIELD],
    ),
    # Citations referenced by AI answers on the given day, with the websites they mention.
    "content_citations": WritesonicEndpointConfig(
        name="content_citations",
        path="/v2/geo/presence/business/export/content/citations",
        primary_keys=["date", "citation_id"],
        daily=True,
        inject_date=True,
        partition_key="date",
        incremental_fields=[_DATE_FIELD],
    ),
    # Keywords/themes extracted from AI answers on the given day.
    "content_keywords": WritesonicEndpointConfig(
        name="content_keywords",
        path="/v2/geo/presence/business/export/content/keywords",
        primary_keys=["date", "id"],
        daily=True,
        inject_date=True,
        partition_key="date",
        incremental_fields=[_DATE_FIELD],
    ),
    # Config dimension tables. Small, no server-side updated-since filter -> full refresh.
    "topics": WritesonicEndpointConfig(
        name="topics",
        path="/v2/geo/presence/business/export/config/topics",
        primary_keys=["topic_id"],
        partition_key="created_at",
    ),
    "platforms": WritesonicEndpointConfig(
        name="platforms",
        path="/v2/geo/presence/business/export/config/platforms",
        primary_keys=["platform_id"],
    ),
    "websites": WritesonicEndpointConfig(
        name="websites",
        path="/v2/geo/presence/business/export/config/websites",
        primary_keys=["website_id"],
        partition_key="created_at",
    ),
    "prompts": WritesonicEndpointConfig(
        name="prompts",
        path="/v2/geo/presence/business/export/config/prompts",
        primary_keys=["prompt_id"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(WRITESONIC_ENDPOINTS.keys())

# Only the daily export endpoints have a genuine server-side date filter (the required `date`
# param); the config exports return `created_at`/`updated_at` but expose no updated-since filter.
SUPPORTS_INCREMENTAL: set[str] = {name for name, cfg in WRITESONIC_ENDPOINTS.items() if cfg.daily}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in WRITESONIC_ENDPOINTS.items()
}
