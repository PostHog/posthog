from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PandaDocEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # Body key the list of rows lives under (every list endpoint wraps in "results").
    data_key: str = "results"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental cursor field to the server-side query param that filters on it
    # (e.g. date_modified -> modified_from). Only documents expose these filters.
    incremental_params: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Some endpoints (contacts, members) return the full list without pagination.
    paginated: bool = True


PANDADOC_ENDPOINTS: dict[str, PandaDocEndpointConfig] = {
    "documents": PandaDocEndpointConfig(
        name="documents",
        path="/documents",
        partition_key="date_created",
        incremental_params={
            "date_modified": "modified_from",
            "date_created": "created_from",
        },
        incremental_fields=[
            {
                "label": "date_modified",
                "type": IncrementalFieldType.DateTime,
                "field": "date_modified",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "date_created",
                "type": IncrementalFieldType.DateTime,
                "field": "date_created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "templates": PandaDocEndpointConfig(
        name="templates",
        path="/templates",
    ),
    "forms": PandaDocEndpointConfig(
        name="forms",
        path="/forms",
    ),
    "contacts": PandaDocEndpointConfig(
        name="contacts",
        path="/contacts",
        paginated=False,
    ),
    "members": PandaDocEndpointConfig(
        name="members",
        path="/members",
        primary_key="user_id",
        paginated=False,
    ),
    "document_folders": PandaDocEndpointConfig(
        name="document_folders",
        path="/documents/folders",
        primary_key="uuid",
    ),
    "template_folders": PandaDocEndpointConfig(
        name="template_folders",
        path="/templates/folders",
        primary_key="uuid",
    ),
}

ENDPOINTS = tuple(PANDADOC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PANDADOC_ENDPOINTS.items() if config.incremental_fields
}
