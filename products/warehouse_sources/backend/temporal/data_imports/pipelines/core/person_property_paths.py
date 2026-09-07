"""S3 layout for the person-property staging and dedup-snapshot folders.

Both the sink that stages rows during a warehouse run and the sync that consumes them derive their
prefixes from here, so the two can never drift apart. Kept in its own module so the sink — which both
the data-import and the data-modeling write path build — doesn't pull in the sync's heavier imports.
"""

from django.conf import settings

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import WarehouseBinding


def binding_path_segment(binding: WarehouseBinding) -> str:
    """The folder segment identifying one binding's staged rows and snapshot.

    A schema keeps the bare id it has always used, so folders written before materialized views were
    supported still resolve. A view gets a prefixed segment, which also keeps the two id spaces from
    colliding.
    """
    if binding.is_saved_query:
        return f"model_{binding.id}"
    return binding.id


def binding_staged_prefix(team_id: int, binding: WarehouseBinding) -> str:
    """Every staged job folder for one binding — the parent the sink sweeps abandoned siblings from."""
    return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_sync/{team_id}/{binding_path_segment(binding)}"


def job_staged_prefix(team_id: int, binding: WarehouseBinding, job_id: str) -> str:
    """Where one run's staged row projections live."""
    return f"{binding_staged_prefix(team_id, binding)}/{job_id}"


def snapshot_prefix(team_id: int, binding: WarehouseBinding, source_id: str) -> str:
    """Where one source's last-sent bundle hashes live, per binding."""
    return (
        f"{settings.DATAWAREHOUSE_BUCKET}/person_property_snapshot/"
        f"{team_id}/{source_id}/{binding_path_segment(binding)}"
    )
