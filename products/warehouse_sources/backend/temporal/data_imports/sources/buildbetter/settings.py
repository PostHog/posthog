from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updated_at"
CREATED_AT = "created_at"
ID = "id"

INTERVIEW_ID = "interview_id"
INTERVIEW_CREATED_AT = "interview_created_at"
INTERVIEW_UPDATED_AT = "interview_updated_at"
EXTRACTION_ID = "extraction_id"
EXTRACTION_CREATED_AT = "extraction_created_at"
SENTENCE_INDEX = "sentence_index"
TOPIC_ID = "topic_id"
TAG_ID = "tag_id"
TYPE_ID = "type_id"

BUILDBETTER_API_URL = "https://api.buildbetter.app/v1/graphql"
BUILDBETTER_DEFAULT_PAGE_SIZE = 1000


def _incremental_datetime_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


INCREMENTAL_UPDATED_AT = _incremental_datetime_field(UPDATED_AT)
INCREMENTAL_CREATED_AT = _incremental_datetime_field(CREATED_AT)
INCREMENTAL_INTERVIEW_UPDATED_AT = _incremental_datetime_field(INTERVIEW_UPDATED_AT)
INCREMENTAL_EXTRACTION_CREATED_AT = _incremental_datetime_field(EXTRACTION_CREATED_AT)


@dataclass(frozen=True)
class BuildBetterNestedConfig:
    """A table built from a nested relation of a parent query, one row per nested item.

    BuildBetter exposes attendees, transcript sentences, tags and the topic and type lookups only
    as relations of `interview` / `extraction`, so these tables page their parent query and
    flatten the relation, carrying the parent's identifier and timestamps onto every row.
    """

    nested_field: str
    parent_columns: dict[str, str]
    unwrap_field: str | None = None
    unwrap_prefix: str = ""
    index_column: str | None = None
    # An object relationship resolves to one record rather than a list, so the record's own
    # fields become the row and `unwrap_prefix` applies to them directly.
    single: bool = False


@dataclass(frozen=True)
class BuildBetterEndpointConfig:
    incremental_fields: list[IncrementalField]
    graphql_query_name: str | None = None
    page_size: int = BUILDBETTER_DEFAULT_PAGE_SIZE
    primary_keys: list[str] = field(default_factory=lambda: [ID])
    nested: BuildBetterNestedConfig | None = None
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_AT])


INTERVIEW_PARENT_COLUMNS = {
    ID: INTERVIEW_ID,
    CREATED_AT: INTERVIEW_CREATED_AT,
    UPDATED_AT: INTERVIEW_UPDATED_AT,
}

BUILDBETTER_ENDPOINTS: dict[str, BuildBetterEndpointConfig] = {
    "interviews": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        page_size=100,
        partition_keys=[CREATED_AT],
    ),
    "interview_attendees": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_INTERVIEW_UPDATED_AT,
        page_size=100,
        primary_keys=[INTERVIEW_ID, ID],
        nested=BuildBetterNestedConfig(
            nested_field="attendees",
            parent_columns=INTERVIEW_PARENT_COLUMNS,
        ),
        partition_keys=[INTERVIEW_CREATED_AT],
    ),
    "interview_sentences": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_INTERVIEW_UPDATED_AT,
        page_size=25,
        # The API exposes no sentence identifier, so a sentence is keyed by its position in the
        # transcript, which the query orders by start time.
        primary_keys=[INTERVIEW_ID, SENTENCE_INDEX],
        nested=BuildBetterNestedConfig(
            nested_field="sentences",
            parent_columns=INTERVIEW_PARENT_COLUMNS,
            index_column=SENTENCE_INDEX,
        ),
        partition_keys=[INTERVIEW_CREATED_AT],
    ),
    "interview_tags": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_INTERVIEW_UPDATED_AT,
        page_size=500,
        primary_keys=[INTERVIEW_ID, TAG_ID],
        nested=BuildBetterNestedConfig(
            nested_field="tags",
            parent_columns=INTERVIEW_PARENT_COLUMNS,
            unwrap_field="tag",
            unwrap_prefix="tag_",
        ),
        partition_keys=[INTERVIEW_CREATED_AT],
    ),
    "interview_types": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_INTERVIEW_UPDATED_AT,
        page_size=500,
        primary_keys=[INTERVIEW_ID, TYPE_ID],
        nested=BuildBetterNestedConfig(
            nested_field="type",
            parent_columns=INTERVIEW_PARENT_COLUMNS,
            unwrap_prefix="type_",
            single=True,
        ),
        partition_keys=[INTERVIEW_CREATED_AT],
    ),
    "extractions": BuildBetterEndpointConfig(
        graphql_query_name="extraction",
        incremental_fields=INCREMENTAL_CREATED_AT,
        partition_keys=[CREATED_AT],
    ),
    "extraction_topics": BuildBetterEndpointConfig(
        graphql_query_name="extraction",
        incremental_fields=INCREMENTAL_EXTRACTION_CREATED_AT,
        page_size=500,
        primary_keys=[EXTRACTION_ID, TOPIC_ID],
        nested=BuildBetterNestedConfig(
            nested_field="topics",
            parent_columns={ID: EXTRACTION_ID, CREATED_AT: EXTRACTION_CREATED_AT},
            unwrap_field="topic",
            unwrap_prefix="topic_",
        ),
        partition_keys=[EXTRACTION_CREATED_AT],
    ),
    "extraction_types": BuildBetterEndpointConfig(
        graphql_query_name="extraction",
        incremental_fields=INCREMENTAL_EXTRACTION_CREATED_AT,
        page_size=500,
        primary_keys=[EXTRACTION_ID, TYPE_ID],
        nested=BuildBetterNestedConfig(
            nested_field="types",
            parent_columns={ID: EXTRACTION_ID, CREATED_AT: EXTRACTION_CREATED_AT},
            unwrap_field="type",
            unwrap_prefix="type_",
        ),
        partition_keys=[EXTRACTION_CREATED_AT],
    ),
    "documents": BuildBetterEndpointConfig(
        graphql_query_name="document",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        page_size=100,
        partition_keys=[CREATED_AT],
    ),
    "persons": BuildBetterEndpointConfig(
        graphql_query_name="person",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "companies": BuildBetterEndpointConfig(
        graphql_query_name="company",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
}

ENDPOINTS = tuple(BUILDBETTER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUILDBETTER_ENDPOINTS.items()
}
