from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from unittest.mock import patch

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceAuth,
    ServiceCredential,
    ServiceCredentialConnect,
)
from products.managed_warehouse.backend.logic import sql_editor_credentials
from products.managed_warehouse.backend.logic.sql_editor_credentials import (
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    ServiceCredentialCache,
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
            host="warehouse.dw.us.postwh.com",
            port=5432,
            database="ducklake",
            sslmode="require",
        ),
    )


def test_concurrent_callers_share_one_in_flight_mint() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    mint_started = Event()
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

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
        assert mint_started.wait(timeout=5)
        second = executor.submit(cache.get, "org-1", 2, principal=SQL_EDITOR_PRINCIPAL)
        allow_mint.set()

    assert first.result().credential_id == "svc_one"
    assert second.result().credential_id == "svc_one"
    assert mint_count == 1


def test_principals_never_share_cached_credentials_within_an_organization() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted_for: list[str] = []

    def mint(_organization_id: str, _team_id: int, principal: str) -> ServiceCredential:
        minted_for.append(principal)
        return _credential(f"svc_{len(minted_for)}", now + timedelta(minutes=15))

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)
    user_one = "posthog:sql-editor:team:1:user:1"
    user_two = "posthog:sql-editor:team:1:user:2"

    assert cache.get("org-1", 1, principal=user_one).credential_id == "svc_1"
    assert cache.get("org-1", 1, principal=user_two).credential_id == "svc_2"
    assert cache.get("org-1", 1, principal=user_one).credential_id == "svc_1"
    assert minted_for == [user_one, user_two]


def test_lifecycle_generations_never_share_cached_credentials_for_the_same_principal() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted: list[str] = []

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        credential_id = f"svc_{len(minted) + 1}"
        minted.append(credential_id)
        return _credential(credential_id, now + timedelta(minutes=15))

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    first = cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL, lifecycle_generation=3)
    same_generation = cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL, lifecycle_generation=3)
    reprovisioned = cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL, lifecycle_generation=5)

    assert first.credential_id == "svc_1"
    assert same_generation.credential_id == "svc_1"
    assert reprovisioned.credential_id == "svc_2"
    assert minted == ["svc_1", "svc_2"]


def test_replaces_a_credential_before_expiry_with_an_independent_mint() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    minted = [
        _credential("svc_old", now + timedelta(minutes=2)),
        _credential("svc_new", now + timedelta(minutes=15)),
    ]

    cache = ServiceCredentialCache(mint=lambda _organization_id, _team_id, _principal: minted.pop(0), now=lambda: now)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_old"
    now += timedelta(seconds=61)
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_new"
    assert minted == []


def test_uses_an_unexpired_cached_credential_during_a_mint_outage_but_fails_after_expiry() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = _credential("svc_old", now + timedelta(minutes=2))
    mint_count = 0

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count
        mint_count += 1
        if mint_count == 1:
            return original
        raise ServiceCredentialUnavailable("control plane unavailable")

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    now += timedelta(seconds=61)
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    now += timedelta(seconds=60)
    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)


def test_failed_early_replacement_is_backed_off_while_cached_credential_remains_valid() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = _credential("svc_old", now + timedelta(minutes=2))
    mint_count = 0

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count
        mint_count += 1
        if mint_count == 1:
            return original
        raise ServiceCredentialUnavailable("control plane unavailable")

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    now += timedelta(seconds=61)
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    assert mint_count == 2


def test_unexpected_early_replacement_failure_serves_and_backs_off_an_unexpired_credential() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = _credential("svc_old", now + timedelta(minutes=2))
    mint_count = 0

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count
        mint_count += 1
        if mint_count == 1:
            return original
        raise RuntimeError("unexpected control-plane client failure")

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    now += timedelta(seconds=61)
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    assert mint_count == 2


def test_stalled_refresh_for_one_organization_does_not_block_another() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    org_one_started = Event()
    release_org_one = Event()

    def mint(organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        if organization_id == "org-1":
            org_one_started.set()
            assert release_org_one.wait(timeout=5)
        return _credential(f"svc_{organization_id}", now + timedelta(minutes=15))

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        org_one = executor.submit(cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
        assert org_one_started.wait(timeout=5)
        org_two = executor.submit(cache.get, "org-2", 2, principal=SQL_EDITOR_PRINCIPAL)
        assert org_two.result(timeout=1).credential_id == "svc_org-2"
        release_org_one.set()

    assert org_one.result().credential_id == "svc_org-1"


def test_per_organization_singleflight_state_is_bounded() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    mint_count = 0

    def mint(organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count
        mint_count += 1
        return _credential(f"svc_{organization_id}_{mint_count}", now + timedelta(minutes=15))

    cache = ServiceCredentialCache(mint=mint, now=lambda: now, maxsize=1)

    cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    cache.get("org-2", 2, principal=SQL_EDITOR_PRINCIPAL)
    cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    assert mint_count == 3


def test_in_use_state_cannot_be_evicted_and_is_evictable_after_release() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state_leased = Event()
    release_state = Event()
    mint_counts: dict[str, int] = {}

    def mint(organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        mint_counts[organization_id] = mint_counts.get(organization_id, 0) + 1
        return _credential(f"svc_{organization_id}", now + timedelta(minutes=15))

    cache = ServiceCredentialCache(mint=mint, now=lambda: now, maxsize=1)
    original_state_for = cache._state_for
    first_org_one_lookup = True

    def pausing_state_for(cache_key: sql_editor_credentials._CredentialCacheKey):
        nonlocal first_org_one_lookup
        state = original_state_for(cache_key)
        if (
            cache_key.organization_id == "org-1"
            and cache_key.principal == SQL_EDITOR_PRINCIPAL
            and cache_key.lifecycle_generation == 0
            and first_org_one_lookup
        ):
            first_org_one_lookup = False
            state_leased.set()
            assert release_state.wait(timeout=5)
        return state

    with patch.object(cache, "_state_for", side_effect=pausing_state_for):
        with ThreadPoolExecutor(max_workers=2) as executor:
            org_one = executor.submit(cache.get, "org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
            assert state_leased.wait(timeout=5)
            with pytest.raises(ServiceCredentialUnavailable, match="at capacity"):
                cache.get("org-2", 2, principal=SQL_EDITOR_PRINCIPAL)
            release_state.set()
            assert org_one.result(timeout=5).credential_id == "svc_org-1"

        assert cache.get("org-2", 2, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_org-2"

    assert mint_counts == {"org-1": 1, "org-2": 1}


def test_sql_editor_mint_uses_a_short_request_timeout() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with patch(
        "products.managed_warehouse.backend.logic.sql_editor_credentials.mint_service_credential",
        return_value=_credential("svc_one", now + timedelta(minutes=15)),
    ) as mint:
        sql_editor_credentials._mint_sql_editor_credential("org-1", 1, SQL_EDITOR_PRINCIPAL)

    assert mint.call_args.kwargs["timeout_seconds"] == 3
    assert mint.call_args.kwargs["principal"] == SQL_EDITOR_PRINCIPAL


def test_does_not_return_a_credential_that_expires_during_a_failed_replacement() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = _credential("svc_old", now + timedelta(minutes=2))
    mint_count = 0

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        nonlocal mint_count, now
        mint_count += 1
        if mint_count == 1:
            return original
        now += timedelta(minutes=1)
        raise ServiceCredentialUnavailable("control plane unavailable")

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL) is original
    now += timedelta(seconds=61)
    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)


def test_failure_state_does_not_retain_exception_tracebacks_or_secret_bearing_locals() -> None:
    def malformed(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        malformed_payload = {"credential_secret": "must-not-remain-reachable"}
        assert malformed_payload
        raise ServiceCredentialUnavailable("malformed control-plane response: must-not-remain-reachable")

    cache = ServiceCredentialCache(mint=malformed)

    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    state = next(iter(cache._states.values()))
    assert not any(isinstance(value, BaseException) for value in vars(state).values())
    assert "must-not-remain-reachable" not in repr(vars(state))


def test_unexpected_refresh_replaces_stale_failure_state_and_is_backed_off() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    failures = [
        ServiceCredentialUnavailable("old unavailable failure"),
        RuntimeError("new unexpected failure"),
    ]

    def mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        raise failures.pop(0)

    cache = ServiceCredentialCache(mint=mint, now=lambda: now)

    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    now += timedelta(seconds=6)
    with pytest.raises(ServiceCredentialUnavailable, match="unexpected"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    with pytest.raises(ServiceCredentialUnavailable, match="unexpected"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)

    assert failures == []


def test_insecure_connect_bundle_is_not_cached_and_the_next_call_can_recover() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    insecure = ServiceCredential(
        credential_id="svc_insecure",
        credential_secret="secret-insecure",
        expires_at=now + timedelta(minutes=15),
        connect=ServiceCredentialConnect(
            host="warehouse.dw.us.postwh.com",
            port=5432,
            database="ducklake",
            sslmode="prefer",
        ),
    )
    minted = [insecure, _credential("svc_secure", now + timedelta(minutes=15))]
    cache = ServiceCredentialCache(mint=lambda _organization_id, _team_id, _principal: minted.pop(0), now=lambda: now)

    with pytest.raises(ServiceCredentialUnavailable, match="service credential mint unavailable"):
        cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL)
    now += timedelta(seconds=6)

    assert cache.get("org-1", 1, principal=SQL_EDITOR_PRINCIPAL).credential_id == "svc_secure"
    assert minted == []


def test_dynamic_source_fails_closed_when_no_credential_can_be_minted(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        raise ServiceCredentialUnavailable("control plane unavailable")

    monkeypatch.setattr(
        sql_editor_credentials,
        "_service_credential_cache",
        ServiceCredentialCache(mint=unavailable),
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
    def unexpected_mint(_organization_id: str, _team_id: int, _principal: str) -> ServiceCredential:
        raise AssertionError("legacy sources must not mint service credentials")

    monkeypatch.setattr(
        sql_editor_credentials,
        "_service_credential_cache",
        ServiceCredentialCache(mint=unexpected_mint),
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


def test_dynamic_connection_carries_required_sslmode() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cache = ServiceCredentialCache(
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


def test_dynamic_connection_rejects_an_insecure_control_plane_sslmode() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    credential = _credential("svc_one", now + timedelta(minutes=15))
    credential = ServiceCredential(
        credential_id=credential.credential_id,
        credential_secret=credential.credential_secret,
        expires_at=credential.expires_at,
        connect=ServiceCredentialConnect(
            host=credential.connect.host,
            port=credential.connect.port,
            database=credential.connect.database,
            sslmode="prefer",
        ),
    )
    cache = ServiceCredentialCache(mint=lambda _organization_id, _team_id, _principal: credential, now=lambda: now)
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
            credential_cache=cache,
        )


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
