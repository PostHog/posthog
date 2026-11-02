from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionMode
from products.warehouse_sources.backend.types import IncrementalField

PAGE_SIZE = 200


@frozen
class ProductiveEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "created_at"
    partition_mode: PartitionMode = "datetime"


ENDPOINTS: dict[str, ProductiveEndpoint] = {
    "bookings": ProductiveEndpoint(path="bookings"),
    "comments": ProductiveEndpoint(path="comments"),
    "companies": ProductiveEndpoint(path="companies"),
    "contact_entries": ProductiveEndpoint(path="contact_entries", partition_key="id", partition_mode="md5"),
    "deal_statuses": ProductiveEndpoint(path="deal_statuses", partition_key="id", partition_mode="md5"),
    "deals": ProductiveEndpoint(path="deals"),
    "expenses": ProductiveEndpoint(path="expenses"),
    "invoices": ProductiveEndpoint(path="invoices"),
    "line_items": ProductiveEndpoint(path="line_items", partition_key="id", partition_mode="md5"),
    "payments": ProductiveEndpoint(path="payments", partition_key="id", partition_mode="md5"),
    "people": ProductiveEndpoint(path="people"),
    "pipelines": ProductiveEndpoint(path="pipelines"),
    "projects": ProductiveEndpoint(path="projects"),
    "purchase_orders": ProductiveEndpoint(path="purchase_orders"),
    "service_types": ProductiveEndpoint(path="service_types", partition_key="id", partition_mode="md5"),
    "services": ProductiveEndpoint(path="services", partition_key="id", partition_mode="md5"),
    "task_lists": ProductiveEndpoint(path="task_lists", partition_key="id", partition_mode="md5"),
    "tasks": ProductiveEndpoint(path="tasks"),
    "time_entries": ProductiveEndpoint(path="time_entries"),
    "workflow_statuses": ProductiveEndpoint(path="workflow_statuses", partition_key="id", partition_mode="md5"),
}

# Timestamp filters need live verification before they can safely drive a sync watermark.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
