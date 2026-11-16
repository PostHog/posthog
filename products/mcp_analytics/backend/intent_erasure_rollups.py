from collections.abc import Iterator
from itertools import batched

from django.conf import settings
from django.core.cache import caches

from django_redis import get_redis_connection
from redis import Redis, RedisCluster

from posthog import redis
from posthog.query_cache import storage as query_cache_storage
from posthog.storage.object_storage import ObjectStorage, object_storage_client
from posthog.utils import generate_cache_key_prefix


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
