from collections.abc import Iterator
from itertools import batched

from django.conf import settings
from django.core.cache import caches

from django_redis import get_redis_connection
from redis import Redis, RedisCluster

from posthog import redis
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.clickhouse.workload import Workload
from posthog.models.deletion_targets import DeletionTarget, placement_for
from posthog.query_cache import storage as query_cache_storage
from posthog.storage.object_storage import ObjectStorage, object_storage_client
from posthog.utils import generate_cache_key_prefix

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
    MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
    MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
    MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE,
)
from products.mcp_analytics.backend.facade.contracts import IntentErasure, IntentErasurePending

ROLLUP_TARGETS = (
    DeletionTarget(
        data_table=MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
        read_table=MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
        optional=True,
    ),
    DeletionTarget(
        data_table=MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
        read_table=MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE,
        optional=True,
    ),
)


class IntentCachePurgeIncomplete(RuntimeError):
    pass


def _delete_redis_prefix(client: Redis | RedisCluster, pattern: str) -> None:
    for key in client.scan_iter(match=pattern, count=1000):
        # Keys in the same team can occupy different Redis Cluster slots.
        client.delete(key)
    if next(client.scan_iter(match=pattern, count=1000), None) is not None:
        raise IntentCachePurgeIncomplete("Intent cache entries survived the purge")


def _object_versions(store: ObjectStorage, bucket: str, prefix: str) -> Iterator[dict[str, str]]:
    pages = store.aws_client.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix)
    for page in pages:
        for entry in (*page.get("Versions", ()), *page.get("DeleteMarkers", ())):
            yield {"Key": entry["Key"], "VersionId": entry["VersionId"]}


def _purge_cache_objects(source_team_ids: tuple[int, ...]) -> None:
    store = object_storage_client()
    if not isinstance(store, ObjectStorage):
        raise IntentCachePurgeIncomplete("Object storage cannot verify intent cache erasure")
    bucket = settings.QUERY_CACHE_S3_BUCKET
    versioning = store.aws_client.get_bucket_versioning(Bucket=bucket)
    versioned = versioning.get("Status") in ("Enabled", "Suspended")
    for team_id in source_team_ids:
        prefix = f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/"
        if versioned:
            for versions in batched(_object_versions(store, bucket, prefix), 1000, strict=False):
                response = store.aws_client.delete_objects(
                    Bucket=bucket, Delete={"Objects": list(versions), "Quiet": True}
                )
                if response.get("Errors"):
                    raise IntentCachePurgeIncomplete("Intent cache object versions could not be removed")
            if next(_object_versions(store, bucket, prefix), None) is not None:
                raise IntentCachePurgeIncomplete("Intent cache object versions survived the purge")
        else:
            # Shadow uploads and expired Redis pointers leave objects outside the Redis index.
            for keys in batched(store.iter_keys(bucket=bucket, prefix=prefix), 1000, strict=False):
                if store.delete_objects(bucket=bucket, keys=list(keys)):
                    raise IntentCachePurgeIncomplete("Intent cache objects could not be removed")
        if next(store.iter_keys(bucket=bucket, prefix=prefix), None) is not None:
            raise IntentCachePurgeIncomplete("Intent cache objects survived the purge")


def _check_pointer_namespaces(client: Redis | RedisCluster, team_id: int) -> None:
    pattern = query_cache_storage.entry_redis_key(f"{generate_cache_key_prefix(team_id)}*")
    prefix = f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/"
    for key in client.scan_iter(match=pattern, count=1000):
        value = client.get(key)
        if not isinstance(value, bytes) or not query_cache_storage.is_s3_pointer(value):
            continue
        pointer = query_cache_storage.decode_pointer(value)
        if pointer is None or pointer.bucket != settings.QUERY_CACHE_S3_BUCKET or not pointer.key.startswith(prefix):
            # Preserve the pointer: a retry needs its evidence of a namespace outside this sweep.
            raise IntentCachePurgeIncomplete("Intent cache points to an unverified object storage namespace")


def purge_intent_caches(*, source_team_ids: tuple[int, ...]) -> None:
    """Purge project caches only after the coordinator has frozen and drained every producer."""
    if not source_team_ids or any(type(team_id) is not int or team_id <= 0 for team_id in source_team_ids):
        raise ValueError("Intent cache erasure requires a nonempty source team scope")
    try:
        default_client = get_redis_connection("default")
        query_client = query_cache_storage.query_cache_raw_client()
        for team_id in source_team_ids:
            _check_pointer_namespaces(query_client, team_id)
        _purge_cache_objects(source_team_ids)
        for team_id in source_team_ids:
            prefix = generate_cache_key_prefix(team_id)
            _delete_redis_prefix(default_client, caches["default"].make_key(f"{prefix}*"))
            _delete_redis_prefix(query_client, query_cache_storage.entry_redis_key(f"{prefix}*"))
            _delete_redis_prefix(redis.get_client(), f"query_async:{team_id}:*")
    except IntentCachePurgeIncomplete:
        raise
    except Exception as error:
        raise IntentCachePurgeIncomplete("Intent cache erasure could not be verified") from error


def _rollup_rows_remain(target: DeletionTarget, *, cluster: ClickhouseCluster, team_ids: tuple[int, ...]) -> bool:
    placement = placement_for(cluster, target)
    if placement is None:
        return False
    query = Query(
        f"SELECT 1 FROM {settings.CLICKHOUSE_DATABASE}.{target.data_table} WHERE team_id IN %(team_ids)s LIMIT 1",
        {"team_ids": team_ids},
    )
    # Every replica answers, online or not, so a lagging replica cannot hide surviving rows.
    results = placement.cluster.map_hosts_by_role(
        query, placement.cluster.shard_role, workload=Workload.DEFAULT
    ).result()
    if not results:
        raise IntentErasurePending(f"No replica could verify {target.data_table}")
    return any(results.values())


def purge_rollups_and_caches(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> None:
    """Purge and verify the intent rollups and caches of every environment in the erasure.

    Raises IntentErasurePending whenever the purge cannot be proved, and never reopens writes.
    The rollups are rebuilt from source events, so the whole project is purged rather than single rows.
    """
    try:
        purge_intent_caches(source_team_ids=erasure.source_team_ids)
    except IntentCachePurgeIncomplete as error:
        raise IntentErasurePending(str(error)) from error
    # The rollup tables are purged with the shared all-replica ClickHouse purge once the pipeline layer
    # publishes it. Until then a project with rollup rows stays frozen instead of reporting success.
    for target in ROLLUP_TARGETS:
        if _rollup_rows_remain(target, cluster=cluster, team_ids=erasure.source_team_ids):
            raise IntentErasurePending(f"Intent rollup rows remain in {target.data_table}")
