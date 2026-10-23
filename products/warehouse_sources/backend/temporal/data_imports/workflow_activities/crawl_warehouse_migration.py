"""Read a customer's Fivetran account and plan what PostHog creates for each connection.

Runs on the table-metadata worker: it makes only light vendor API calls and must not contend
with the import pipeline. The activity writes the snapshot and items to Postgres and returns
only a count, so no vendor data crosses the Temporal payload boundary.
"""

import json
import uuid
from datetime import timedelta

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.migration.crawl import crawl_migration

WORKFLOW_NAME = "warehouse-migration-crawl"


@frozen
class CrawlWarehouseMigrationInputs:
    team_id: int
    migration_id: uuid.UUID


@activity.defn
async def crawl_warehouse_migration_activity(inputs: CrawlWarehouseMigrationInputs) -> int:
    async with Heartbeater():
        return await database_sync_to_async(crawl_migration, thread_sensitive=False)(
            team_id=inputs.team_id, migration_id=inputs.migration_id
        )


@workflow.defn(name=WORKFLOW_NAME)
class CrawlWarehouseMigrationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CrawlWarehouseMigrationInputs:
        loaded = json.loads(inputs[0])
        return CrawlWarehouseMigrationInputs(team_id=loaded["team_id"], migration_id=uuid.UUID(loaded["migration_id"]))

    @workflow.run
    async def run(self, inputs: CrawlWarehouseMigrationInputs) -> int:
        return await workflow.execute_activity(
            crawl_warehouse_migration_activity,
            inputs,
            # One account can hold hundreds of connections at two API calls each.
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=["FivetranAuthError"]),
        )


@async_to_sync
async def start_crawl(*, team_id: int, migration_id: uuid.UUID) -> str:
    workflow_id = f"{WORKFLOW_NAME}-{migration_id}"
    client: Client = await async_connect()
    await client.start_workflow(
        WORKFLOW_NAME,
        CrawlWarehouseMigrationInputs(team_id=team_id, migration_id=migration_id),
        id=workflow_id,
        task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )
    return workflow_id
