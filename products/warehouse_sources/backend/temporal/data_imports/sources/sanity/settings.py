from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_VERSION = "2026-10-12"
PAGE_SIZE = 100
DISCOVERY_QUERY = 'array::unique(*[!(_type match "system.*") && !(_id in path("_.**"))]._type)'


@frozen
class SanityEndpoint:
    document_type: str
    primary_keys: tuple[str, ...] = ("_id",)
    partition_key: str = "_createdAt"
    incremental_field: str = "_updatedAt"


ENDPOINTS: dict[str, SanityEndpoint] = {
    "sanity.fileAsset": SanityEndpoint(document_type="sanity.fileAsset"),
    "sanity.imageAsset": SanityEndpoint(document_type="sanity.imageAsset"),
}


def document_endpoint(document_type: str) -> SanityEndpoint:
    return ENDPOINTS.get(document_type) or SanityEndpoint(document_type=document_type)


def incremental_fields(endpoint: SanityEndpoint) -> list[IncrementalField]:
    return [
        {
            "label": endpoint.incremental_field,
            "type": IncrementalFieldType.DateTime,
            "field": endpoint.incremental_field,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
