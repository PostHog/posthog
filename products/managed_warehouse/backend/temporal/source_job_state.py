from django.conf import settings
from django.db import close_old_connections

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobUpdate
from products.managed_warehouse.backend.source_job_state import record_source_job_state


@activity.defn
async def record_managed_warehouse_source_job_activity(update: ManagedWarehouseSourceJobUpdate) -> None:
    if not settings.TEST:
        await database_sync_to_async(close_old_connections)()
    await database_sync_to_async(record_source_job_state)(update)
