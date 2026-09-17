from __future__ import annotations

import hmac
import json
import math
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from django.conf import settings

import redis
from cryptography.fernet import InvalidToken
from prometheus_client import Counter
from redis.backoff import NoBackoff
from redis.retry import Retry

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.redis import get_client

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehousePostgresConnection,
    ManagedWarehouseSourceAuth,
    ServiceCredential,
    ServiceCredentialConnect,
)
from products.managed_warehouse.backend.service_credentials import ServiceCredentialUnavailable, mint_service_credential
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
)

SQL_EDITOR_CREDENTIAL_REFRESH_MARGIN = timedelta(minutes=1)
SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS = 3
# The lease safely outlives the mint and bounded Redis operations. Contenders wait only four
# seconds, so a dead owner cannot hold up a query for the full lease.
SQL_EDITOR_CREDENTIAL_LOCK_TIMEOUT_SECONDS = 30
SQL_EDITOR_CREDENTIAL_LOCK_WAIT_SECONDS = SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS + 1
SQL_EDITOR_CREDENTIAL_CACHE_KEY_VERSION = 2

SERVICE_CREDENTIAL_CACHE_EVENTS = Counter(
    "posthog_managed_warehouse_service_credential_cache_events_total",
    "Managed warehouse service credential cache events by low-cardinality outcome.",
    labelnames=["outcome"],
)
CredentialCacheOutcome = Literal[
    "hit",
    "miss",
    "lock_timeout",
    "invalid_payload",
    "redis_error",
    "store_failure",
    "direct_fallback",
]

CredentialMint = Callable[[str, int, str], ServiceCredential]
Clock = Callable[[], datetime]
RedisClient = Callable[[], redis.Redis]

_CREDENTIAL_CACHE_REDIS_URL_POLICY_OPTIONS = {
    "retry",
    "retry_on_error",
    "retry_on_timeout",
    "socket_connect_timeout",
    "socket_timeout",
    "timeout",
}


def _record_cache_event(outcome: CredentialCacheOutcome) -> None:
    SERVICE_CREDENTIAL_CACHE_EVENTS.labels(outcome=outcome).inc()


def _credential_cache_redis_url(redis_url: str) -> str:
    parsed = urlsplit(redis_url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _CREDENTIAL_CACHE_REDIS_URL_POLICY_OPTIONS
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


@lru_cache(maxsize=1)
def _get_credential_cache_redis_client() -> redis.Redis:
    if settings.TEST:
        return get_client()
    return redis.from_url(
        _credential_cache_redis_url(settings.REDIS_URL),
        db=0,
        socket_connect_timeout=settings.MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=settings.MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_READ_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
        retry_on_error=[],
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _mint_sql_editor_credential(organization_id: str, team_id: int, principal: str) -> ServiceCredential:
    return mint_service_credential(
        organization_id,
        team_id,
        principal=principal,
        timeout_seconds=SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS,
    )


@frozen
class _CredentialCacheKey:
    organization_id: str
    principal: str
    lifecycle_generation: int

    def canonical_identity(self) -> str:
        return json.dumps(
            {
                "lifecycle_generation": self.lifecycle_generation,
                "organization_id": self.organization_id,
                "principal": self.principal,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def redis_key(self) -> str:
        digest = hashlib.sha256(self.canonical_identity().encode()).hexdigest()
        return f"managed_warehouse:service_credential:v{SQL_EDITOR_CREDENTIAL_CACHE_KEY_VERSION}:{digest}"


class _CredentialPayloadCodec:
    def __init__(self) -> None:
        self._cipher = EncryptedFieldMixin()

    def encode(self, credential: ServiceCredential, cache_key: _CredentialCacheKey) -> str:
        plaintext = json.dumps(
            {
                "cache_identity": cache_key.canonical_identity(),
                "credential_id": credential.credential_id,
                "credential_secret": credential.credential_secret,
                "expires_at": credential.expires_at.isoformat(),
                "connect": {
                    "host": credential.connect.host,
                    "port": credential.connect.port,
                    "database": credential.connect.database,
                    "sslmode": credential.connect.sslmode,
                },
            },
            separators=(",", ":"),
        )
        return self._cipher.encrypt(plaintext)

    def decode(self, payload: bytes | str, cache_key: _CredentialCacheKey) -> ServiceCredential | None:
        try:
            token = payload.decode() if isinstance(payload, bytes) else payload
            raw = json.loads(self._cipher.decrypt(token))
            identity = raw["cache_identity"]
            if not isinstance(identity, str) or not hmac.compare_digest(identity, cache_key.canonical_identity()):
                return None
            connect = raw["connect"]
            return ServiceCredential(
                credential_id=raw["credential_id"],
                credential_secret=raw["credential_secret"],
                expires_at=datetime.fromisoformat(raw["expires_at"]),
                connect=ServiceCredentialConnect(
                    host=connect["host"],
                    port=connect["port"],
                    database=connect["database"],
                    sslmode=connect["sslmode"],
                ),
            )
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


class RedisServiceCredentialCache:
    def __init__(
        self,
        *,
        mint: CredentialMint = _mint_sql_editor_credential,
        now: Clock = _utcnow,
        redis_client: RedisClient = _get_credential_cache_redis_client,
        codec: _CredentialPayloadCodec | None = None,
    ) -> None:
        self._mint = mint
        self._now = now
        self._redis_client = redis_client
        self._codec = codec or _CredentialPayloadCodec()

    def get(
        self,
        organization_id: str | UUID,
        team_id: int,
        *,
        principal: str,
        lifecycle_generation: int = 0,
    ) -> ServiceCredential:
        cache_key = _CredentialCacheKey(
            organization_id=str(organization_id),
            principal=principal,
            lifecycle_generation=lifecycle_generation,
        )
        redis_key = cache_key.redis_key()

        try:
            client = self._redis_client()
            cached = self._load_cached(client, redis_key, cache_key)
        except Exception:
            return self._mint_fallback(cache_key, team_id, outcome="redis_error")
        if cached is not None:
            return cached

        lock = None
        acquired = False
        try:
            lock = client.lock(
                f"{redis_key}:lock",
                timeout=SQL_EDITOR_CREDENTIAL_LOCK_TIMEOUT_SECONDS,
                blocking_timeout=SQL_EDITOR_CREDENTIAL_LOCK_WAIT_SECONDS,
            )
            acquired = lock.acquire()
        except Exception:
            return self._mint_fallback(cache_key, team_id, outcome="redis_error")

        if not acquired:
            _record_cache_event("lock_timeout")
            try:
                cached = self._load_cached(client, redis_key, cache_key)
            except Exception:
                return self._mint_fallback(cache_key, team_id, outcome="redis_error")
            if cached is not None:
                return cached
            _record_cache_event("direct_fallback")
            return self._mint_direct(cache_key, team_id)

        try:
            try:
                cached = self._load_cached(client, redis_key, cache_key)
            except Exception:
                return self._mint_fallback(cache_key, team_id, outcome="redis_error")
            if cached is not None:
                return cached

            minted = self._mint_direct(cache_key, team_id)
            ttl_seconds = math.floor(
                (minted.expires_at - self._now() - SQL_EDITOR_CREDENTIAL_REFRESH_MARGIN).total_seconds()
            )
            if ttl_seconds <= 0:
                return minted
            try:
                stored = client.set(redis_key, self._codec.encode(minted, cache_key), ex=ttl_seconds)
            except Exception:
                _record_cache_event("store_failure")
                _record_cache_event("direct_fallback")
                return minted
            if not stored:
                _record_cache_event("store_failure")
                _record_cache_event("direct_fallback")
                return minted
            return minted
        finally:
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    _record_cache_event("redis_error")

    def _load_cached(
        self, client: redis.Redis, redis_key: str, cache_key: _CredentialCacheKey
    ) -> ServiceCredential | None:
        payload = client.get(redis_key)
        if payload is None:
            _record_cache_event("miss")
            return None
        credential = self._codec.decode(payload, cache_key)
        if credential is None:
            _record_cache_event("invalid_payload")
            return None
        try:
            self._validate_credential(credential)
        except (ServiceCredentialUnavailable, AttributeError, TypeError):
            _record_cache_event("invalid_payload")
            return None
        if credential.expires_at <= self._now() + SQL_EDITOR_CREDENTIAL_REFRESH_MARGIN:
            _record_cache_event("miss")
            return None
        _record_cache_event("hit")
        return credential

    def _mint_fallback(
        self,
        cache_key: _CredentialCacheKey,
        team_id: int,
        *,
        outcome: Literal["redis_error"],
    ) -> ServiceCredential:
        _record_cache_event(outcome)
        _record_cache_event("direct_fallback")
        return self._mint_direct(cache_key, team_id)

    def _mint_direct(self, cache_key: _CredentialCacheKey, team_id: int) -> ServiceCredential:
        try:
            minted = self._mint(cache_key.organization_id, team_id, cache_key.principal)
            self._validate_credential(minted)
            return minted
        except ServiceCredentialUnavailable:
            raise ServiceCredentialUnavailable("service credential mint unavailable") from None
        except Exception:
            raise ServiceCredentialUnavailable("service credential mint failed unexpectedly") from None

    def _validate_credential(self, credential: ServiceCredential) -> None:
        now = self._now()
        if credential.expires_at.tzinfo is None or credential.expires_at.utcoffset() is None:
            raise ServiceCredentialUnavailable("service credential mint returned an invalid expiry")
        if credential.expires_at <= now:
            raise ServiceCredentialUnavailable("service credential mint returned an expired credential")
        if (
            not isinstance(credential.credential_id, str)
            or not credential.credential_id
            or not isinstance(credential.credential_secret, str)
            or not credential.credential_secret
            or not isinstance(credential.connect.host, str)
            or not credential.connect.host
            or isinstance(credential.connect.port, bool)
            or not isinstance(credential.connect.port, int)
            or not 1 <= credential.connect.port <= 65535
            or not isinstance(credential.connect.database, str)
            or not credential.connect.database
            or credential.connect.sslmode != "require"
        ):
            raise ServiceCredentialUnavailable("SQL editor service credential requires a complete secure sslmode")


_service_credential_cache = RedisServiceCredentialCache()


def _is_dynamic_managed_warehouse_source(source_auth: ManagedWarehouseSourceAuth) -> bool:
    return (
        source_auth.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        and source_auth.system_managed
        and source_auth.credential_kind == MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND
    )


def resolve_managed_warehouse_postgres_connection(
    *,
    source_auth: ManagedWarehouseSourceAuth,
    organization_id: str | UUID,
    team_id: int,
    principal: str,
    credential_cache: RedisServiceCredentialCache | None = None,
) -> ManagedWarehousePostgresConnection | None:
    if not _is_dynamic_managed_warehouse_source(source_auth):
        return None
    if (
        source_auth.lifecycle_generation is None
        or isinstance(source_auth.lifecycle_generation, bool)
        or source_auth.lifecycle_generation < 0
    ):
        raise ServiceCredentialUnavailable("managed warehouse source has no valid lifecycle generation")

    credential = (credential_cache or _service_credential_cache).get(
        organization_id,
        team_id,
        principal=principal,
        lifecycle_generation=source_auth.lifecycle_generation,
    )
    if credential.connect.sslmode != "require":
        raise ServiceCredentialUnavailable("SQL editor service credential requires a secure sslmode")
    return ManagedWarehousePostgresConnection(
        host=credential.connect.host,
        port=credential.connect.port,
        database=credential.connect.database,
        username=credential.credential_id,
        password=credential.credential_secret,
        sslmode=credential.connect.sslmode,
    )
