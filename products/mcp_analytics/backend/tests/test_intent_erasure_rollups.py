from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from fakeredis import FakeRedis
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.dags.tests.conftest import isolated_clickhouse_cluster
from posthog.query_cache.storage import S3BlobPointer, encode_pointer, entry_redis_key
from posthog.storage.object_storage import ObjectStorage, UnavailableStorage
from posthog.utils import generate_cache_key

from products.mcp_analytics.backend import intent_erasure_rollups as erasure
from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
    MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
    MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
)
from products.mcp_analytics.backend.facade.contracts import IntentErasure, IntentErasurePending
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls
from products.mcp_analytics.backend.intent_topics.rollups import insert_hourly_calls


class CacheObjectAPI:
    def __init__(self, *, versioned: bool = False) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.versioned = versioned
        self.fail_listing = False
        self.fail_delete = False
        self.fail_verification = False
        self.deleted = False

    def get_bucket_versioning(self, **kwargs):
        return {"Status": "Enabled"} if self.versioned else {}

    def get_paginator(self, operation):
        owner = self

        class Paginator:
            def paginate(self, *, Bucket, Prefix, **kwargs) -> Iterator[dict]:
                if owner.fail_listing or (owner.deleted and owner.fail_verification):
                    raise RuntimeError("listing unavailable")
                keys = sorted(key for key in owner.objects if key[0].startswith(Prefix))
                for offset in range(0, len(keys), 200):
                    page = keys[offset : offset + 200]
                    if operation == "list_object_versions":
                        yield {
                            "Versions": [
                                {"Key": key, "VersionId": version} for key, version in page if version != "marker"
                            ],
                            "DeleteMarkers": [
                                {"Key": key, "VersionId": version} for key, version in page if version == "marker"
                            ],
                        }
                    else:
                        yield {"Contents": [{"Key": key} for key, version in page if version != "marker"]}

        return Paginator()

    def delete_objects(self, *, Bucket, Delete):
        if self.fail_delete:
            return {"Errors": [{"Key": entry["Key"], "Code": "AccessDenied"} for entry in Delete["Objects"]]}
        for entry in Delete["Objects"]:
            self.objects.pop((entry["Key"], entry.get("VersionId", "null")), None)
        self.deleted = True
        return {}


class _FakeCacheStores:
    def _use_fake_cache_stores(self) -> None:
        self.default_redis = FakeRedis()
        self.query_redis = FakeRedis()
        self.status_redis = FakeRedis()
        self.objects = CacheObjectAPI()
        self.enterContext(patch.object(erasure, "get_redis_connection", return_value=self.default_redis))  # type: ignore[attr-defined]
        self.enterContext(  # type: ignore[attr-defined]
            patch.object(erasure.query_cache_storage, "query_cache_raw_client", return_value=self.query_redis)
        )
        self.enterContext(patch.object(erasure.redis, "get_client", return_value=self.status_redis))  # type: ignore[attr-defined]
        self.enterContext(patch.object(erasure, "object_storage_client", return_value=ObjectStorage(self.objects)))  # type: ignore[attr-defined]


@override_settings(QUERY_CACHE_S3_BUCKET="test-query-cache", OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER="query_cache")
class TestIntentCacheErasure(_FakeCacheStores, SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._use_fake_cache_stores()

    @parameterized.expand([("unversioned", False), ("versioned", True)])
    def test_erases_sibling_copies_and_unreferenced_objects_without_touching_other_projects(
        self, _name: str, versioned: bool
    ) -> None:
        self.objects.versioned = versioned
        for team_id in (71, 72, 710):
            key = generate_cache_key(team_id, "invented intent corpus")
            self.default_redis.set(caches["default"].make_key(key), b"digest")
            self.query_redis.set(entry_redis_key(key), b"response")
            self.status_redis.set(f"query_async:{team_id}:query-id", b"async result")
            for index in range(1001):
                self.objects.objects[(f"query_cache/{team_id}/{index}", "null")] = b"shadow upload"
                if versioned:
                    self.objects.objects[(f"query_cache/{team_id}/{index}", "old")] = b"old version"
            if versioned:
                self.objects.objects[(f"query_cache/{team_id}/deleted", "marker")] = b""

        erasure.purge_intent_caches(source_team_ids=(71, 72))
        erasure.purge_intent_caches(source_team_ids=(71, 72))

        for team_id in (71, 72, 710):
            key = generate_cache_key(team_id, "invented intent corpus")
            remaining = team_id == 710
            assert bool(self.default_redis.exists(caches["default"].make_key(key))) == remaining
            assert bool(self.query_redis.exists(entry_redis_key(key))) == remaining
            assert bool(self.status_redis.exists(f"query_async:{team_id}:query-id")) == remaining
            assert any(key.startswith(f"query_cache/{team_id}/") for key, _ in self.objects.objects) == remaining

    @parameterized.expand([("listing", "fail_listing"), ("delete", "fail_delete"), ("verify", "fail_verification")])
    def test_incomplete_object_storage_proof_raises(self, _name: str, failure: str) -> None:
        self.objects.objects[("query_cache/71/blob", "null")] = b"copied intent"
        setattr(self.objects, failure, True)
        with pytest.raises(erasure.IntentCachePurgeIncomplete):
            erasure.purge_intent_caches(source_team_ids=(71,))

    def test_unavailable_object_storage_is_not_proof_of_absence(self) -> None:
        with patch.object(erasure, "object_storage_client", return_value=UnavailableStorage()):
            with pytest.raises(erasure.IntentCachePurgeIncomplete):
                erasure.purge_intent_caches(source_team_ids=(71,))

    def test_unknown_namespace_keeps_its_pointer_for_the_next_attempt(self) -> None:
        key = entry_redis_key(generate_cache_key(71, "older response"))
        pointer = encode_pointer(S3BlobPointer(bucket="previous-cache-bucket", key="old_cache/71/result"))
        self.query_redis.set(key, pointer)
        with pytest.raises(erasure.IntentCachePurgeIncomplete):
            erasure.purge_intent_caches(source_team_ids=(71,))
        assert self.query_redis.get(key) == pointer

    def test_failed_object_purge_keeps_the_pointer(self) -> None:
        key = entry_redis_key(generate_cache_key(71, "response"))
        pointer = encode_pointer(S3BlobPointer(bucket="test-query-cache", key="query_cache/71/result"))
        self.query_redis.set(key, pointer)
        self.objects.objects[("query_cache/71/result", "null")] = b"copied intent"
        self.objects.fail_delete = True
        with pytest.raises(erasure.IntentCachePurgeIncomplete):
            erasure.purge_intent_caches(source_team_ids=(71,))
        assert self.query_redis.get(key) == pointer

    def test_failed_redis_delete_does_not_report_completion(self) -> None:
        key = caches["default"].make_key(generate_cache_key(71, "digest"))
        self.default_redis.set(key, b"copied intent")
        with patch.object(self.default_redis, "delete", return_value=0):
            with pytest.raises(erasure.IntentCachePurgeIncomplete):
                erasure.purge_intent_caches(source_team_ids=(71,))
        assert self.default_redis.get(key) == b"copied intent"

    @parameterized.expand([("empty", ()), ("invalid", (0,)), ("boolean", (True,))])
    def test_requires_an_explicit_nonempty_scope(self, _name: str, team_ids: tuple[int, ...]) -> None:
        with pytest.raises(ValueError):
            erasure.purge_intent_caches(source_team_ids=team_ids)


def _unused_team_ids() -> tuple[int, int, int]:
    # The cluster fixture does not clear the rollup tables, so each test takes team ids no earlier run wrote.
    base = 2_000_000_000 + (uuid4().int % 10**9) * 3
    return base, base + 1, base + 2


def _insert_rollup(table: str, team_id: int) -> None:
    if table == "hourly":
        hour = datetime(2026, 11, 1, 12, tzinfo=UTC)
        insert_hourly_calls(
            team_id,
            [HourlyCalls(hour=hour, hash="invented-intent", tool="query-trends", calls=1, conversations=(1,))],
            now=hour,
        )
    else:
        sync_execute(
            f"INSERT INTO {MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE} (team_id, day, tool, topic_id, calls, conversation_hashes, outlier_calls, intents, inserted_at) VALUES",
            [(team_id, date(2026, 11, 1), "query-trends", "topic", 1, [1], 0, 1, datetime(2026, 11, 2, tzinfo=UTC))],
            settings={"insert_distributed_sync": 1},
        )


@override_settings(QUERY_CACHE_S3_BUCKET="test-query-cache", OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER="query_cache")
class TestPurgeRollupsAndCaches(_FakeCacheStores, SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._use_fake_cache_stores()
        self.cluster = self.enterContext(isolated_clickhouse_cluster())
        self.erased, self.sibling, self.other = _unused_team_ids()
        self.erasure = IntentErasure(
            project_id=self.erased, invalidation_id=uuid4(), source_team_ids=(self.erased, self.sibling)
        )

    def _rollup_teams(self) -> set[tuple[str, int]]:
        teams = (self.erased, self.sibling, self.other)
        return {
            (table, team_id)
            for table in (MCP_INTENT_CALLS_HOURLY_DATA_TABLE, MCP_INTENT_TOPIC_DAILY_DATA_TABLE)
            for (team_id,) in sync_execute(
                f"SELECT DISTINCT team_id FROM {table} WHERE team_id IN %(teams)s", {"teams": teams}
            )
        }

    def test_purges_the_project_rollups_and_keeps_other_projects(self) -> None:
        for team_id in (self.erased, self.sibling, self.other):
            _insert_rollup("hourly", team_id)
            _insert_rollup("daily", team_id)
        self.default_redis.set(
            caches["default"].make_key(generate_cache_key(self.erased, "invented intent corpus")), b"digest"
        )

        erasure.purge_rollups_and_caches(erasure=self.erasure, cluster=self.cluster)

        assert self._rollup_teams() == {
            (MCP_INTENT_CALLS_HOURLY_DATA_TABLE, self.other),
            (MCP_INTENT_TOPIC_DAILY_DATA_TABLE, self.other),
        }
        assert not self.default_redis.exists(
            caches["default"].make_key(generate_cache_key(self.erased, "invented intent corpus"))
        )

    def test_an_unproven_cache_purge_keeps_the_erasure_pending(self) -> None:
        self.objects.fail_listing = True

        with pytest.raises(IntentErasurePending):
            erasure.purge_rollups_and_caches(erasure=self.erasure, cluster=self.cluster)
