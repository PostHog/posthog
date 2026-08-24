from django.conf import settings

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import WarehouseBinding
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_paths import (
    binding_path_segment,
)


def binding_staged_prefix(team_id: int, binding: WarehouseBinding) -> str:
    return f"{settings.DATAWAREHOUSE_BUCKET}/account_property_sync/{team_id}/{binding_path_segment(binding)}"


def job_staged_prefix(team_id: int, binding: WarehouseBinding, job_id: str) -> str:
    return f"{binding_staged_prefix(team_id, binding)}/{job_id}"


def snapshot_prefix(team_id: int, binding: WarehouseBinding, source_id: str, segment: str) -> str:
    return (
        f"{settings.DATAWAREHOUSE_BUCKET}/account_property_snapshot/"
        f"{team_id}/{source_id}/{segment}/{binding_path_segment(binding)}"
    )


def completion_prefix(team_id: int, binding: WarehouseBinding, job_id: str) -> str:
    return f"{settings.DATAWAREHOUSE_BUCKET}/account_property_runs/{team_id}/{binding_path_segment(binding)}/{job_id}"
