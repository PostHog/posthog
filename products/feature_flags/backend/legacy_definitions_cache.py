import json
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from posthoganalytics import capture_exception

from posthog.models.team import Team
from posthog.storage import object_storage
from posthog.storage.hypercache import (
    _HYPER_CACHE_EMPTY_VALUE,
    _REDIS_READ_ERRORS,
    HYPERCACHE_CACHE_COUNTER,
    HyperCache,
    HyperCacheDependencyUnavailable,
    HyperCacheStoreMissing,
    KeyType,
)

from products.feature_flags.backend.legacy_definitions import sanitize_legacy_definitions

PROVENANCE_OBJECT = "flags_with_cohorts.provenance.json"
PROVENANCE_HEADER = "x-posthog-legacy-definitions"


class LegacyDefinitionsHyperCache(HyperCache):
    # Old builders can erase an excluded target before caching its dependent.
    # Only a content-bound publication record proves the complete graph was guarded.
    def _provenance_key(self, key: KeyType) -> str:
        return self.get_cache_key(key).rsplit("/", 1)[0] + "/" + PROVENANCE_OBJECT

    def _verified_payload(self, raw: str | None, provenance: str | None) -> dict[str, Any] | None:
        if not isinstance(raw, str) or not isinstance(provenance, str):
            return None
        try:
            if json.loads(provenance) != {"etag": self._compute_etag(raw)}:
                return None
            payload = json.loads(raw)
            sanitized = sanitize_legacy_definitions(payload)
            return payload if sanitized == payload else None
        except (TypeError, ValueError):
            return None

    def get_etag(self, key: KeyType) -> str | None:
        try:
            values = self.cache_client.get_many([self.get_etag_key(key), self._provenance_key(key)])
            etag = values.get(self.get_etag_key(key))
            provenance = values.get(self._provenance_key(key))
            if etag and provenance and json.loads(provenance) == {"etag": etag}:
                return etag
        except (*_REDIS_READ_ERRORS, TypeError, ValueError):
            pass
        return None

    def _secondary_etag_matches(self, key: KeyType, etag: str) -> bool:
        if self.secondary_cache_client is None:
            return True
        try:
            values = self.secondary_cache_client.get_many([self.get_etag_key(key), self._provenance_key(key)])
            return values.get(self.get_etag_key(key)) == etag and json.loads(
                values.get(self._provenance_key(key)) or "null"
            ) == {"etag": etag}
        except (*_REDIS_READ_ERRORS, TypeError, ValueError):
            return False

    def set_cache_value(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: int | None = None,
        skip_if_unchanged: bool = False,
    ) -> int | None:
        if isinstance(data, dict):
            data = sanitize_legacy_definitions(data)
        return super().set_cache_value(key, data, ttl, skip_if_unchanged)

    def delete_cache_entry(self, key: KeyType, kinds: list[str] | None = None) -> None:
        super().delete_cache_entry(key, kinds)
        kinds = kinds or ["redis", "s3"]
        provenance_key = self._provenance_key(key)
        if "redis" in kinds:
            self._mirror_to_secondary(lambda client: client.delete(provenance_key))
            self.cache_client.delete(provenance_key)
        if "s3" in kinds and self.s3_enabled:
            object_storage.delete(provenance_key)

    def _set_cache_value_redis(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: int | None = None,
        json_data: str | None = None,
    ) -> int | None:
        if isinstance(data, dict):
            data = sanitize_legacy_definitions(data)
            json_data = json.dumps(data, sort_keys=True)
        elif data is not None and not isinstance(data, HyperCacheStoreMissing):
            raise ValueError("Invalid legacy definitions envelope")
        # Publishing proof last makes interrupted writes fail closed at readers.
        size = super()._set_cache_value_redis(key, data, ttl, json_data)
        provenance_key = self._provenance_key(key)
        if json_data is not None:
            provenance = json.dumps({"etag": self._compute_etag(json_data)})
            timeout = ttl if ttl is not None else self.cache_ttl
            self._mirror_to_secondary(lambda client: client.set(provenance_key, provenance, timeout=timeout))
            self.cache_client.set(provenance_key, provenance, timeout=timeout)
        else:
            self._mirror_to_secondary(lambda client: client.delete(provenance_key))
            self.cache_client.delete(provenance_key)
        return size

    def _set_cache_value_s3(
        self, key: KeyType, data: dict | None | HyperCacheStoreMissing, ttl: int | None = None
    ) -> None:
        if isinstance(data, dict):
            data = sanitize_legacy_definitions(data)
        super()._set_cache_value_s3(key, data, ttl)
        if isinstance(data, dict):
            etag = self._compute_etag(json.dumps(data, sort_keys=True))
            object_storage.write(self._provenance_key(key), json.dumps({"etag": etag}))
        else:
            object_storage.delete(self._provenance_key(key))

    def get_from_cache_with_source(self, key: KeyType) -> tuple[dict | None, str]:
        cache_key = self.get_cache_key(key)
        provenance_key = self._provenance_key(key)
        try:
            values = self.cache_client.get_many([cache_key, provenance_key])
            if values.get(cache_key) == _HYPER_CACHE_EMPTY_VALUE:
                HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()
                return None, "redis"
            payload = self._verified_payload(values.get(cache_key), values.get(provenance_key))
            if payload is not None:
                HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()
                return payload, "redis"
        except _REDIS_READ_ERRORS as error:
            capture_exception(error)
        if self.s3_enabled:
            try:
                payload = self._verified_payload(
                    object_storage.read(cache_key, missing_ok=True),
                    object_storage.read(provenance_key, missing_ok=True),
                )
                if payload is not None:
                    self._set_cache_value_redis(key, payload)
                    HYPERCACHE_CACHE_COUNTER.labels(result="hit_s3", namespace=self.namespace, value=self.value).inc()
                    return payload, "s3"
            except (object_storage.ObjectStorageError, BotoCoreError, ClientError, ValueError) as error:
                capture_exception(error)
        try:
            loaded_payload = self.load_fn(key)
            if isinstance(loaded_payload, HyperCacheStoreMissing):
                self._set_cache_value_redis(key, None)
                HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
                return None, "db"
            payload = sanitize_legacy_definitions(loaded_payload)
            self._set_cache_value_redis(key, payload)
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
            return payload, "db"
        except HyperCacheDependencyUnavailable:
            HYPERCACHE_CACHE_COUNTER.labels(
                result="dependency_unavailable", namespace=self.namespace, value=self.value
            ).inc()
            return None, "dependency_unavailable"

    # Keep HyperCache's existing positional contract for the shared cache verifier.
    def batch_get_from_cache(
        self, teams: list[Team]
    ) -> dict[int, tuple[dict | None, str, str | None]]:  # nosemgrep: tuple-return-prefer-dataclass
        if not teams:
            return {}
        keys = [
            key
            for team in teams
            for key in (self.get_cache_key(team), self._provenance_key(team), self.get_etag_key(team))
        ]
        try:
            values = self.cache_client.get_many(keys)
        except _REDIS_READ_ERRORS as error:
            capture_exception(error)
            values = {}
        results: dict[int, tuple[dict | None, str, str | None]] = {}
        hit_count = 0
        for team in teams:
            raw = values.get(self.get_cache_key(team))
            etag = values.get(self.get_etag_key(team)) if self.enable_etag else None
            if raw == _HYPER_CACHE_EMPTY_VALUE:
                results[team.id] = (None, "redis", etag)
                hit_count += 1
                continue
            payload = self._verified_payload(raw, values.get(self._provenance_key(team)))
            results[team.id] = (payload, "redis", etag) if payload is not None else (None, "miss", etag)
            hit_count += payload is not None
        if hit_count:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc(
                hit_count
            )
        if len(teams) > hit_count:
            HYPERCACHE_CACHE_COUNTER.labels(result="batch_miss", namespace=self.namespace, value=self.value).inc(
                len(teams) - hit_count
            )
        return results
