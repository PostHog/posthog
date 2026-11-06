from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

import fakeredis
from prometheus_client import REGISTRY

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceAuth,
    ServiceCredential,
    ServiceCredentialConnect,
)
from products.managed_warehouse.backend.logic import sql_editor_credentials
from products.managed_warehouse.backend.logic.sql_editor_credentials import (
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    RedisServiceCredentialCache,
    resolve_managed_warehouse_postgres_connection,
)
from products.managed_warehouse.backend.service_credentials import ServiceCredentialUnavailable
from products.warehouse_sources.backend.facade.models import MANAGED_WAREHOUSE_SOURCE_PREFIX

SQL_EDITOR_PRINCIPAL = "posthog:sql-editor:team:1:user:1"


def _credential(credential_id: str, expires_at: datetime) -> ServiceCredential:
    return ServiceCredential(
        credential_id=credential_id,
        credential_secret=f"secret-{credential_id}",
        expires_at=expires_at,
        connect=ServiceCredentialConnect(
            host="warehouse.example.com",
            port=5432,
            database="ducklake",
            sslmode="require",
        ),
    )


def _redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


def _cache(
    client: fakeredis.FakeRedis,
    *,
    mint: sql_editor_credentials.CredentialMint,
    now: sql_editor_credentials.Clock,
) -> RedisServiceCredentialCache:
    return RedisServiceCredentialCache(redis_client=lambda: client, mint=mint, now=now)


def _cache_metric(outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_managed_warehouse_service_credential_cache_events_total",
            {"outcome": outcome},
        )
        or 0
    )


def test_cache_instances_share_one_in_flight_mint() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    server = fakeredis.FakeServer()
    owner_client = fakeredis.FakeRedis(server=server)
    follower_client = fakeredis.FakeRedis(server=server)
    mint_started = Event()
    follower_failed_lock_attempt = Event()
    allow_mint = Event()
    mint_count = 0
    count_lock = Lock()

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count
        with count_lock:
            mint_count += 1
        mint_started.set()
        assert allow_mint.wait(timeout=5)
        return _credential("svc_one", now + timedelta(minutes=15))

    first_cache = _cache(owner_client, mint=mint, now=lambda: now)
    second_cache = _cache(follower_client, mint=mint, now=lambda: now)
    original_set = follower_client.set

    def signaling_set(name, *args, **kwargs):
        result = original_set(name, *args, **kwargs)
        if str(name).endswith(":lock") and kwargs.get("nx") and not result:
            follower_failed_lock_attempt.set()
        return result

    with patch.object(follower_client, "set", side_effect=signaling_set):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(first_cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
            assert mint_started.wait(timeout=5)
            second = executor.submit(second_cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
            assert follower_failed_lock_attempt.wait(timeout=5)
            allow_mint.set()

    assert first.result().credential_id == "svc_one"
    assert second.result().credential_id == "svc_one"
    assert mint_count == 1


@pytest.mark.parametrize(
    "target",
    [
        ("org-2", SQL_EDITOR_PRINCIPAL, 1),
        ("org-1", "posthog:sql-editor:team:1:user:2", 1),
        ("org-1", SQL_EDITOR_PRINCIPAL, 2),
    ],
)
def test_encrypted_payload_cannot_be_transplanted_between_cache_identities(target) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    minted: list[str] = []

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        credential_id = f"svc_{len(minted) + 1}"
        minted.append(credential_id)
        return _credential(credential_id, now + timedelta(minutes=15))

    cache = _cache(client, mint=mint, now=lambda: now)
    cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL, lifecycle_generation=1)
    source_key = client.keys("*")[0]
    source_payload = client.get(source_key)
    assert source_payload is not None
    cache.get(target[0], 1, principal=target[1], lifecycle_generation=target[2])
    target_key = next(key for key in client.keys("*") if key != source_key)
    client.set(target_key, source_payload, ex=60)

    invalid_before = _cache_metric("invalid_payload")
    replacement = cache.get(target[0], 1, principal=target[1], lifecycle_generation=target[2])

    assert replacement.credential_id == "svc_3"
    assert minted == ["svc_1", "svc_2", "svc_3"]
    assert _cache_metric("invalid_payload") == invalid_before + 2


@override_settings(
    TEST=False,
    REDIS_URL="redis://cache.example.com:6379",
    MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_CONNECT_TIMEOUT_SECONDS=0.25,
    MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_READ_TIMEOUT_SECONDS=0.5,
)
def test_dedicated_redis_client_uses_short_timeouts_without_retries() -> None:
    sql_editor_credentials._get_credential_cache_redis_client.cache_clear()
    try:
        with patch.object(sql_editor_credentials.redis, "from_url") as from_url:
            sql_editor_credentials._get_credential_cache_redis_client()

        kwargs = from_url.call_args.kwargs
        assert from_url.call_args.args == ("redis://cache.example.com:6379",)
        assert kwargs["socket_connect_timeout"] == 0.25
        assert kwargs["socket_timeout"] == 0.5
        assert kwargs["retry_on_error"] == []
        assert kwargs["retry"]._retries == 0
    finally:
        sql_editor_credentials._get_credential_cache_redis_client.cache_clear()


@override_settings(
    TEST=False,
    REDIS_URL=(
        "redis://cache-user:cache-password@cache.example.com:6379/3"
        "?socket_timeout=99&socket_connect_timeout=98&timeout=97"
        "&retry_on_timeout=true&retry_on_error=TimeoutError&retry=unsafe&health_check_interval=7"
    ),
    MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_CONNECT_TIMEOUT_SECONDS=0.5,
    MANAGED_WAREHOUSE_CREDENTIAL_CACHE_REDIS_READ_TIMEOUT_SECONDS=0.5,
)
def test_dedicated_redis_client_url_cannot_override_timeout_or_retry_policy() -> None:
    sql_editor_credentials._get_credential_cache_redis_client.cache_clear()
    try:
        client = sql_editor_credentials._get_credential_cache_redis_client()
        connection_kwargs = client.connection_pool.connection_kwargs

        assert connection_kwargs["socket_connect_timeout"] == 0.5
        assert connection_kwargs["socket_timeout"] == 0.5
        assert connection_kwargs["retry_on_error"] == []
        assert connection_kwargs["retry"]._retries == 0
        assert connection_kwargs["username"] == "cache-user"
        assert connection_kwargs["password"] == "cache-password"
        assert connection_kwargs["db"] == 3
        assert connection_kwargs["health_check_interval"] == 7
    finally:
        sql_editor_credentials._get_credential_cache_redis_client.cache_clear()


@pytest.mark.parametrize(
    "first,second",
    [
        (("org-1", SQL_EDITOR_PRINCIPAL, 1), ("org-2", SQL_EDITOR_PRINCIPAL, 1)),
        (
            ("org-1", "posthog:sql-editor:team:1:user:1", 1),
            ("org-1", "posthog:sql-editor:team:1:user:2", 1),
        ),
        (("org-1", SQL_EDITOR_PRINCIPAL, 1), ("org-1", SQL_EDITOR_PRINCIPAL, 2)),
    ],
)
def test_organization_principal_and_generation_have_independent_credentials(first, second) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted: list[str] = []

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        credential_id = f"svc_{len(minted) + 1}"
        minted.append(credential_id)
        return _credential(credential_id, now + timedelta(minutes=15))

    cache = _cache(_redis(), mint=mint, now=lambda: now)

    first_credential = cache.get(first[0], 1, principal=first[1], lifecycle_generation=first[2])
    second_credential = cache.get(second[0], 1, principal=second[1], lifecycle_generation=second[2])
    hits_before = _cache_metric("hit")
    reused_first = cache.get(first[0], 1, principal=first[1], lifecycle_generation=first[2])

    assert first_credential.credential_id == "svc_1"
    assert second_credential.credential_id == "svc_2"
    assert reused_first.credential_id == "svc_1"
    assert minted == ["svc_1", "svc_2"]
    assert _cache_metric("hit") == hits_before + 1


def test_mint_for_one_key_does_not_block_another_key() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first_started = Event()
    release_first = Event()

    def mint(organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        if organization_id == "org-1":
            first_started.set()
            assert release_first.wait(timeout=5)
        return _credential(f"svc_{organization_id}", now + timedelta(minutes=15))

    client = _redis()
    first_cache = _cache(client, mint=mint, now=lambda: now)
    second_cache = _cache(client, mint=mint, now=lambda: now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
        assert first_started.wait(timeout=5)
        second = executor.submit(second_cache.get, "org-2", 2, principal=SQL_EDITOR_PRINCIPAL)
        assert second.result(timeout=1).credential_id == "svc_org-2"
        release_first.set()

    assert first.result().credential_id == "svc_org-1"


def test_cached_payload_is_encrypted_and_expires_before_the_credential() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: _credential("svc_visible_id", now + timedelta(minutes=15)),
        now=lambda: now,
    )

    misses_before = _cache_metric("miss")
    result = cache.get("org-sensitive", 1, principal=SQL_EDITOR_PRINCIPAL, lifecycle_generation=7)

    assert result.credential_id == "svc_visible_id"
    keys = client.keys("*")
    assert len(keys) == 1
    payload = client.get(keys[0])
    assert payload is not None
    redis_material = b" ".join([*keys, payload])
    assert b"org-sensitive" not in redis_material
    assert SQL_EDITOR_PRINCIPAL.encode() not in redis_material
    assert b"secret-svc_visible_id" not in redis_material
    assert b"svc_visible_id" not in redis_material
    assert client.ttl(keys[0]) == 14 * 60
    assert _cache_metric("miss") == misses_before + 2


def test_refresh_margin_replaces_with_a_new_independent_credential() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted = [
        _credential("svc_old", now + timedelta(minutes=2)),
        _credential("svc_new", now + timedelta(minutes=15)),
    ]
    cache = _cache(
        _redis(),
        mint=lambda _organization_id, _team_id, _principal: minted.pop(0),
        now=lambda: now,
    )

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_old"
    now += timedelta(seconds=61)
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_new"
    assert minted == []


def test_malformed_cached_payload_is_replaced() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    minted = [
        _credential("svc_first", now + timedelta(minutes=15)),
        _credential("svc_recovered", now + timedelta(minutes=15)),
    ]
    first_cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: minted.pop(0),
        now=lambda: now,
    )
    first_cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    cache_key = client.keys("*")[0]
    client.set(cache_key, b"not-an-encrypted-credential", ex=60)
    second_cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: minted.pop(0),
        now=lambda: now,
    )

    recovered = second_cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    assert recovered.credential_id == "svc_recovered"
    assert minted == []
    assert client.get(cache_key) != b"not-an-encrypted-credential"


@pytest.mark.parametrize(
    "redis_error",
    [ConnectionError("redis unavailable"), sql_editor_credentials.redis.exceptions.TimeoutError("redis timed out")],
)
def test_redis_get_failure_mints_each_time_without_local_reuse(redis_error: Exception) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted: list[str] = []

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        credential_id = f"svc_{len(minted) + 1}"
        minted.append(credential_id)
        return _credential(credential_id, now + timedelta(minutes=15))

    client = _redis()
    cache = _cache(client, mint=mint, now=lambda: now)
    redis_errors_before = _cache_metric("redis_error")
    direct_fallbacks_before = _cache_metric("direct_fallback")

    with patch.object(client, "get", side_effect=redis_error):
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_1"
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_2"
    assert minted == ["svc_1", "svc_2"]
    assert client.keys("*") == []
    assert _cache_metric("redis_error") == redis_errors_before + 2
    assert _cache_metric("direct_fallback") == direct_fallbacks_before + 2


def test_redis_client_failure_mints_without_caching() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    mint = Mock(return_value=_credential("svc_direct", now + timedelta(minutes=15)))
    cache = RedisServiceCredentialCache(
        redis_client=Mock(side_effect=ConnectionError("redis unavailable")),
        mint=mint,
        now=lambda: now,
    )

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_direct"
    mint.assert_called_once()


@pytest.mark.parametrize("failure_point", ["lock", "acquire"])
def test_redis_lock_failure_mints_without_caching(failure_point: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    if failure_point == "lock":
        lock_patch = patch.object(client, "lock", side_effect=ConnectionError("redis unavailable"))
    else:
        lock = Mock()
        lock.acquire.side_effect = ConnectionError("redis unavailable")
        lock_patch = patch.object(client, "lock", return_value=lock)
    cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: _credential("svc_direct", now + timedelta(minutes=15)),
        now=lambda: now,
    )

    with lock_patch:
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_direct"
    assert client.keys("*") == []


def test_redis_set_failure_returns_the_mint_without_caching() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    original_set = client.set

    def fail_cache_set(name, *args, **kwargs):
        if str(name).endswith(":lock"):
            return original_set(name, *args, **kwargs)
        raise ConnectionError("redis unavailable")

    cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: _credential("svc_direct", now + timedelta(minutes=15)),
        now=lambda: now,
    )
    store_failures_before = _cache_metric("store_failure")
    direct_fallbacks_before = _cache_metric("direct_fallback")

    with patch.object(client, "set", side_effect=fail_cache_set):
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_direct"
    assert client.keys("*") == []
    assert _cache_metric("store_failure") == store_failures_before + 1
    assert _cache_metric("direct_fallback") == direct_fallbacks_before + 1


def test_redis_release_failure_does_not_fail_the_minted_credential() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    lock = Mock()
    lock.acquire.return_value = True
    lock.release.side_effect = ConnectionError("redis unavailable")
    cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: _credential("svc_direct", now + timedelta(minutes=15)),
        now=lambda: now,
    )
    redis_errors_before = _cache_metric("redis_error")

    with patch.object(client, "lock", return_value=lock):
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_direct"
    assert len(client.keys("*")) == 1
    assert _cache_metric("redis_error") == redis_errors_before + 1


def test_lock_timeout_after_an_owner_crash_mints_without_caching() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    lock = Mock()
    lock.acquire.return_value = False
    minted: list[str] = []

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        credential_id = f"svc_{len(minted) + 1}"
        minted.append(credential_id)
        return _credential(credential_id, now + timedelta(minutes=15))

    cache = _cache(client, mint=mint, now=lambda: now)
    lock_timeouts_before = _cache_metric("lock_timeout")
    direct_fallbacks_before = _cache_metric("direct_fallback")

    with patch.object(client, "lock", return_value=lock):
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_1"
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_2"
    assert client.keys("*") == []
    assert minted == ["svc_1", "svc_2"]
    assert _cache_metric("lock_timeout") == lock_timeouts_before + 2
    assert _cache_metric("direct_fallback") == direct_fallbacks_before + 2


def test_lock_timeout_records_contention_when_the_owner_published_a_credential() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    mint = Mock(return_value=_credential("svc_shared", now + timedelta(minutes=15)))
    cache = _cache(client, mint=mint, now=lambda: now)
    cached = cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    cache_key = client.keys("*")[0]
    payload = client.get(cache_key)
    assert payload is not None
    lock = Mock()
    lock.acquire.return_value = False
    lock_timeouts_before = _cache_metric("lock_timeout")
    hits_before = _cache_metric("hit")
    direct_fallbacks_before = _cache_metric("direct_fallback")

    with (
        patch.object(client, "get", side_effect=[None, payload]),
        patch.object(client, "lock", return_value=lock),
    ):
        result = cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    assert result.credential_id == cached.credential_id
    mint.assert_called_once()
    assert _cache_metric("lock_timeout") == lock_timeouts_before + 1
    assert _cache_metric("hit") == hits_before + 1
    assert _cache_metric("direct_fallback") == direct_fallbacks_before


def test_cached_credential_is_not_used_after_redis_becomes_unavailable() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    client = _redis()
    minted = [
        _credential("svc_cached", now + timedelta(minutes=15)),
        _credential("svc_direct", now + timedelta(minutes=15)),
    ]
    cache = _cache(
        client,
        mint=lambda _organization_id, _team_id, _principal: minted.pop(0),
        now=lambda: now,
    )

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_cached"
    with patch.object(client, "get", side_effect=ConnectionError("redis unavailable")):
        assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_direct"
    assert minted == []


def test_insecure_minted_credential_is_never_cached() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    insecure = ServiceCredential(
        credential_id="svc_insecure",
        credential_secret="secret-insecure",
        expires_at=now + timedelta(minutes=15),
        connect=ServiceCredentialConnect(
            host="warehouse.example.com",
            port=5432,
            database="ducklake",
            sslmode="prefer",
        ),
    )
    client = _redis()
    cache = _cache(client, mint=lambda _organization_id, _team_id, _principal: insecure, now=lambda: now)

    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    assert client.keys("*") == []


def test_sql_editor_mint_uses_a_short_request_timeout() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with patch(
        "products.managed_warehouse.backend.logic.sql_editor_credentials.mint_service_credential",
        return_value=_credential("svc_one", now + timedelta(minutes=15)),
    ) as mint:
        sql_editor_credentials._mint_sql_editor_credential("org-1", 1, SQL_EDITOR_PRINCIPAL)

    assert mint.call_args.kwargs["timeout_seconds"] == 3
    assert mint.call_args.kwargs["principal"] == SQL_EDITOR_PRINCIPAL


def test_dynamic_source_fails_closed_when_no_credential_can_be_minted(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        raise ServiceCredentialUnavailable("control plane unavailable")

    monkeypatch.setattr(
        sql_editor_credentials,
        "_service_credential_cache",
        RedisServiceCredentialCache(redis_client=_redis, mint=unavailable),
    )
    source_auth = ManagedWarehouseSourceAuth(
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        system_managed=True,
        credential_kind=MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
        lifecycle_generation=1,
    )

    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        resolve_managed_warehouse_postgres_connection(
            source_auth=source_auth,
            organization_id="org-1",
            team_id=1,
            principal=SQL_EDITOR_PRINCIPAL,
        )


def test_unmarked_source_uses_legacy_connection_details_without_minting(monkeypatch: pytest.MonkeyPatch) -> None:
    mint = Mock(side_effect=AssertionError("legacy sources must not mint service credentials"))
    monkeypatch.setattr(
        sql_editor_credentials,
        "_service_credential_cache",
        RedisServiceCredentialCache(redis_client=_redis, mint=mint),
    )
    source_auth = ManagedWarehouseSourceAuth(
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        system_managed=True,
        credential_kind=None,
        lifecycle_generation=None,
    )

    assert (
        resolve_managed_warehouse_postgres_connection(
            source_auth=source_auth,
            organization_id="org-1",
            team_id=1,
            principal=SQL_EDITOR_PRINCIPAL,
        )
        is None
    )
    mint.assert_not_called()


def test_dynamic_connection_carries_required_sslmode() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cache = _cache(
        _redis(),
        mint=lambda _organization_id, _team_id, _principal: _credential("svc_one", now + timedelta(minutes=15)),
        now=lambda: now,
    )
    source_auth = ManagedWarehouseSourceAuth(
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        system_managed=True,
        credential_kind=MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
        lifecycle_generation=1,
    )

    connection = resolve_managed_warehouse_postgres_connection(
        source_auth=source_auth,
        organization_id="org-1",
        team_id=1,
        principal=SQL_EDITOR_PRINCIPAL,
        credential_cache=cache,
    )

    assert connection is not None
    assert connection.sslmode == "require"


def test_dynamic_source_without_a_lifecycle_generation_fails_closed() -> None:
    source_auth = ManagedWarehouseSourceAuth(
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        system_managed=True,
        credential_kind=MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
        lifecycle_generation=None,
    )

    with pytest.raises(ServiceCredentialUnavailable, match="lifecycle generation"):
        resolve_managed_warehouse_postgres_connection(
            source_auth=source_auth,
            organization_id="org-1",
            team_id=1,
            principal=SQL_EDITOR_PRINCIPAL,
        )
