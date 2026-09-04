from urllib.parse import urlparse

from django.conf import settings

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import WarehouseBinding
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_paths import (
    binding_path_segment,
)


def _warehouse_delta_prefix() -> str:
    parsed = urlparse(settings.BUCKET_URL)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("BUCKET_URL must be an S3 URI")
    return f"{parsed.netloc}{parsed.path.rstrip('/')}"


def binding_staged_prefix(team_id: int, binding: WarehouseBinding) -> str:
    return f"{_warehouse_delta_prefix()}/account_property_sync/{team_id}/{binding_path_segment(binding)}"


def job_staged_prefix(team_id: int, binding: WarehouseBinding, job_id: str) -> str:
    return f"{binding_staged_prefix(team_id, binding)}/{job_id}"


def snapshot_prefix(team_id: int, binding: WarehouseBinding, source_id: str, segment: str) -> str:
    return (
        f"{_warehouse_delta_prefix()}/account_property_snapshot/"
        f"{team_id}/{source_id}/{segment}/{binding_path_segment(binding)}"
    )


def completion_prefix(team_id: int, binding: WarehouseBinding, job_id: str) -> str:
    return f"{_warehouse_delta_prefix()}/account_property_runs/{team_id}/{binding_path_segment(binding)}/{job_id}"
