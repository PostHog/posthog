import json
from typing import Any

from django.conf import settings

from posthoganalytics import capture_exception

from posthog.models.team import Team
from posthog.storage import object_storage
from posthog.storage.hypercache import (
    _HYPER_CACHE_EMPTY_VALUE,
    _REDIS_READ_ERRORS,
    HYPERCACHE_CACHE_COUNTER,
    HYPERCACHE_MIRROR_FAILURE_COUNTER,
    HyperCache,
    HyperCacheStoreMissing,
    KeyType,
)

from products.feature_flags.backend.legacy_definitions import (
    sanitize_legacy_definitions,
    validate_legacy_definitions_envelope,
)

PROVENANCE_OBJECT = "flags_with_cohorts.provenance.json"
PROVENANCE_HEADER = "x-posthog-legacy-definitions"


class LegacyDefinitionsHyperCache(HyperCache):
    """Cache definitions filtered for legacy SDKs with a companion hash of the body.

    Producers write the hash after excluding unsupported or malformed flags and
    their dependents. Old producers can remove a target without its dependents,
    so readers need this record to identify bodies written by a filtering producer.
    Python and Rust readers verify the hash and envelope without filtering again.
    """

    def _provenance_key(self, key: KeyType) -> str:
        return self.get_cache_key(key).rsplit("/", 1)[0] + "/" + PROVENANCE_OBJECT

    def _provenance_record(self, etag: str) -> str:
        return json.dumps({"etag": etag})

    def _proven_etag(self, provenance: str | None) -> str | None:
        record = json.loads(provenance) if provenance else None
        etag = record.get("etag") if isinstance(record, dict) else None
        return etag if isinstance(etag, str) else None

    def _delete_redis_provenance(self, key: KeyType) -> None:
        provenance_key = self._provenance_key(key)
        self._mirror_to_secondary(lambda client: client.delete(provenance_key))
        self.cache_client.delete(provenance_key)

    def _verified_payload(self, raw: str | None, provenance: str | None) -> dict[str, Any] | None:
        if not isinstance(raw, str) or not isinstance(provenance, str):
            return None
        try:
            if self._proven_etag(provenance) != self._compute_etag(raw):
                return None
            payload = json.loads(raw)
            validate_legacy_definitions_envelope(payload)
            return payload
        except (TypeError, ValueError):
            return None

    def get_etag(self, key: KeyType) -> str | None:
        if not settings.FLAG_DEFINITIONS_REQUIRE_PROVENANCE:
            return super().get_etag(key)
        return self.get_verified_etag(key)

    def get_verified_etag(self, key: KeyType) -> str | None:
        try:
            values = self.cache_client.get_many([self.get_etag_key(key), self._provenance_key(key)])
            etag = values.get(self.get_etag_key(key))
            provenance = values.get(self._provenance_key(key))
            if etag and self._proven_etag(provenance) == etag:
                return etag
        except (*_REDIS_READ_ERRORS, TypeError, ValueError) as error:
            capture_exception(error)
        return None

    def _secondary_etag_matches(self, key: KeyType, etag: str) -> bool:
        if self.secondary_cache_client is None:
            return True
        try:
            values = self.secondary_cache_client.get_many([self.get_etag_key(key), self._provenance_key(key)])
            return (
                values.get(self.get_etag_key(key)) == etag
                and self._proven_etag(values.get(self._provenance_key(key))) == etag
            )
        except (*_REDIS_READ_ERRORS, TypeError, ValueError) as error:
            HYPERCACHE_MIRROR_FAILURE_COUNTER.labels(namespace=self.namespace, value=self.value).inc()
            capture_exception(error)
            return False

    def set_cache_value(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: int | None = None,
        skip_if_unchanged: bool = False,
        *,
        publish_provenance: bool = True,
    ) -> int | None:
        if isinstance(data, dict):
            data = sanitize_legacy_definitions(data)
        # An unchanged legacy body still needs publication provenance during warmup.
        if (
            not settings.FLAG_DEFINITIONS_REQUIRE_PROVENANCE
            and skip_if_unchanged
            and self.expiry_sorted_set_key
            and self.get_verified_etag(key) is None
        ):
            skip_if_unchanged = False
        return super().set_cache_value(key, data, ttl, skip_if_unchanged, publish_provenance=publish_provenance)

    def delete_cache_entry(self, key: KeyType, kinds: list[str] | None = None) -> None:
        super().delete_cache_entry(key, kinds)
        kinds = kinds or ["redis", "s3"]
        provenance_key = self._provenance_key(key)
        if "redis" in kinds:
            self._delete_redis_provenance(key)
        if "s3" in kinds and self.s3_enabled:
            object_storage.delete(provenance_key)

    def _set_cache_value_redis(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: int | None = None,
        json_data: str | None = None,
        *,
        publish_provenance: bool = True,
    ) -> int | None:
        if isinstance(data, dict):
            if json_data is None:
                data = sanitize_legacy_definitions(data)
                json_data = json.dumps(data, sort_keys=True)
        elif data is not None and not isinstance(data, HyperCacheStoreMissing):
            raise ValueError("Invalid legacy definitions envelope")
        if not publish_provenance:
            self._delete_redis_provenance(key)
            return super()._set_cache_value_redis(key, data, ttl, json_data)
        # Publishing proof last makes interrupted writes fail closed at readers.
        size = super()._set_cache_value_redis(key, data, ttl, json_data)
        provenance_key = self._provenance_key(key)
        if json_data is not None:
            provenance = self._provenance_record(self._compute_etag(json_data))
            timeout = ttl if ttl is not None else self.cache_ttl
            self._mirror_to_secondary(lambda client: client.set(provenance_key, provenance, timeout=timeout))
            self.cache_client.set(provenance_key, provenance, timeout=timeout)
        else:
            self._delete_redis_provenance(key)
        return size

    def _set_cache_value_s3(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: int | None = None,
        json_data: str | None = None,
        *,
        publish_provenance: bool = True,
    ) -> None:
        if json_data is None and isinstance(data, dict):
            json_data = json.dumps(data, sort_keys=True)
        if not publish_provenance:
            object_storage.delete(self._provenance_key(key))
            return super()._set_cache_value_s3(key, data, ttl, json_data)
        super()._set_cache_value_s3(key, data, ttl, json_data)
        if json_data is not None:
            object_storage.write(self._provenance_key(key), self._provenance_record(self._compute_etag(json_data)))
        else:
            object_storage.delete(self._provenance_key(key))

    def _read_payload(self, raw: str | None, provenance: str | None) -> dict[str, Any] | None:
        if settings.FLAG_DEFINITIONS_REQUIRE_PROVENANCE:
            return self._verified_payload(raw, provenance)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else None
            return payload if isinstance(payload, dict) else None
        except ValueError:
            return None

    def _read_redis_payload(self, key: KeyType) -> dict | None | HyperCacheStoreMissing:
        cache_key = self.get_cache_key(key)
        provenance_key = self._provenance_key(key)
        values = self.cache_client.get_many([cache_key, provenance_key])
        if values.get(cache_key) == _HYPER_CACHE_EMPTY_VALUE:
            return HyperCacheStoreMissing()
        return self._read_payload(values.get(cache_key), values.get(provenance_key))

    def _read_s3_payload(self, key: KeyType) -> dict | None:
        raw = object_storage.read(self.get_cache_key(key), missing_ok=True)
        provenance = object_storage.read(self._provenance_key(key), missing_ok=True)
        payload = self._read_payload(raw, provenance)
        if payload is not None:
            verified = self._verified_payload(raw, provenance) is not None
            self._set_cache_value_redis(key, payload, json_data=raw if verified else None, publish_provenance=verified)
        return payload

    def _load_payload(self, key: KeyType) -> dict | None | HyperCacheStoreMissing:
        payload = super()._load_payload(key)
        if isinstance(payload, HyperCacheStoreMissing):
            return payload
        if not isinstance(payload, dict):
            raise ValueError("Invalid legacy definitions envelope")
        return sanitize_legacy_definitions(payload)

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
