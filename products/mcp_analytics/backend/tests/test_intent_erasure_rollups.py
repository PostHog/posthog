from collections.abc import Iterator

import pytest
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from fakeredis import FakeRedis
from parameterized import parameterized

from posthog.query_cache.storage import S3BlobPointer, encode_pointer, entry_redis_key
from posthog.storage.object_storage import ObjectStorage, UnavailableStorage
from posthog.utils import generate_cache_key

from products.mcp_analytics.backend import intent_erasure_rollups as erasure


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


@override_settings(QUERY_CACHE_S3_BUCKET="test-query-cache", OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER="query_cache")
class TestIntentCacheErasure(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.default_redis = FakeRedis()
        self.query_redis = FakeRedis()
        self.status_redis = FakeRedis()
        self.objects = CacheObjectAPI()
        self.enterContext(patch.object(erasure, "get_redis_connection", return_value=self.default_redis))
        self.enterContext(
            patch.object(erasure.query_cache_storage, "query_cache_raw_client", return_value=self.query_redis)
        )
        self.enterContext(patch.object(erasure.redis, "get_client", return_value=self.status_redis))
        self.enterContext(patch.object(erasure, "object_storage_client", return_value=ObjectStorage(self.objects)))

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
