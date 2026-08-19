from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Condition, Lock
from uuid import UUID

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehousePostgresConnection,
    ManagedWarehouseSourceAuth,
    ServiceCredential,
)
from products.managed_warehouse.backend.service_credentials import ServiceCredentialUnavailable, mint_service_credential
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
)

SQL_EDITOR_CREDENTIAL_REFRESH_MARGIN = timedelta(minutes=1)
SQL_EDITOR_CREDENTIAL_RETRY_BACKOFF = timedelta(seconds=5)
SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS = 3
SQL_EDITOR_CREDENTIAL_CACHE_SIZE = 512

CredentialMint = Callable[[str, int, str], ServiceCredential]
Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _mint_sql_editor_credential(organization_id: str, team_id: int, principal: str) -> ServiceCredential:
    return mint_service_credential(
        organization_id,
        team_id,
        principal=principal,
        timeout_seconds=SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS,
    )


@dataclass(frozen=False)
class _OrganizationCredentialState:
    condition: Condition = field(default_factory=Condition)
    credential: ServiceCredential | None = None
    refreshing: bool = False
    retry_after: datetime | None = None
    failure_category: str | None = None
    failure_message: str | None = None
    leases: int = 0


@frozen
class _CredentialCacheKey:
    organization_id: str
    principal: str
    lifecycle_generation: int


class ServiceCredentialCache:
    def __init__(
        self,
        *,
        mint: CredentialMint = _mint_sql_editor_credential,
        now: Clock = _utcnow,
        maxsize: int = SQL_EDITOR_CREDENTIAL_CACHE_SIZE,
    ) -> None:
        self._mint = mint
        self._now = now
        self._maxsize = maxsize
        self._states: OrderedDict[_CredentialCacheKey, _OrganizationCredentialState] = OrderedDict()
        self._states_lock = Lock()

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
        state = self._state_for(cache_key)
        try:
            return self._get_from_state(state, cache_key, team_id)
        finally:
            self._release_state(cache_key, state)

    def _get_from_state(
        self, state: _OrganizationCredentialState, cache_key: _CredentialCacheKey, team_id: int
    ) -> ServiceCredential:
        with state.condition:
            now = self._now()
            cached = state.credential
            if cached is not None and cached.expires_at > now + SQL_EDITOR_CREDENTIAL_REFRESH_MARGIN:
                return cached

            if state.retry_after is not None and now < state.retry_after:
                if cached is not None and cached.expires_at > now:
                    return cached
                raise self._failure_from_state(state, "service credential mint is backed off")

            if state.refreshing:
                if cached is not None and cached.expires_at > now:
                    return cached
                refresh_finished = state.condition.wait_for(
                    lambda: not state.refreshing,
                    timeout=SQL_EDITOR_CREDENTIAL_MINT_TIMEOUT_SECONDS + 1,
                )
                if not refresh_finished:
                    raise ServiceCredentialUnavailable("service credential mint timed out")
                now = self._now()
                cached = state.credential
                if cached is not None and cached.expires_at > now:
                    return cached
                raise self._failure_from_state(state, "service credential mint failed")

            state.refreshing = True

        try:
            minted = self._mint(cache_key.organization_id, team_id, cache_key.principal)
            self._validate_minted_credential(minted)
        except ServiceCredentialUnavailable:
            with state.condition:
                state.refreshing = False
                state.failure_category = "unavailable"
                # The control-plane exception may have parsed response data in its
                # traceback or message. Retain only a fixed, public-safe summary.
                state.failure_message = "service credential mint unavailable"
                state.retry_after = self._now() + SQL_EDITOR_CREDENTIAL_RETRY_BACKOFF
                cached = state.credential
                state.condition.notify_all()
                if cached is not None and cached.expires_at > self._now():
                    return cached
            raise ServiceCredentialUnavailable(state.failure_message) from None
        except Exception:
            with state.condition:
                state.refreshing = False
                state.failure_category = "unexpected"
                state.failure_message = "service credential mint failed unexpectedly"
                state.retry_after = self._now() + SQL_EDITOR_CREDENTIAL_RETRY_BACKOFF
                cached = state.credential
                state.condition.notify_all()
                if cached is not None and cached.expires_at > self._now():
                    return cached
            raise ServiceCredentialUnavailable(state.failure_message) from None
        except BaseException:
            with state.condition:
                state.refreshing = False
                state.failure_category = "interrupted"
                state.failure_message = "service credential mint was interrupted"
                state.retry_after = self._now() + SQL_EDITOR_CREDENTIAL_RETRY_BACKOFF
                state.condition.notify_all()
            raise

        with state.condition:
            state.credential = minted
            state.refreshing = False
            state.retry_after = None
            state.failure_category = None
            state.failure_message = None
            state.condition.notify_all()
        return minted

    def _validate_minted_credential(self, credential: ServiceCredential) -> None:
        if credential.expires_at <= self._now():
            raise ServiceCredentialUnavailable("service credential mint returned an expired credential")
        if (
            not credential.connect.host
            or credential.connect.port <= 0
            or not credential.connect.database
            or credential.connect.sslmode != "require"
        ):
            raise ServiceCredentialUnavailable("SQL editor service credential requires a complete secure sslmode")

    @staticmethod
    def _failure_from_state(state: _OrganizationCredentialState, fallback: str) -> ServiceCredentialUnavailable:
        return ServiceCredentialUnavailable(state.failure_message or fallback)

    def _state_for(self, cache_key: _CredentialCacheKey) -> _OrganizationCredentialState:
        with self._states_lock:
            state = self._states.get(cache_key)
            if state is not None:
                self._states.move_to_end(cache_key)
                state.leases += 1
                return state

            if len(self._states) >= self._maxsize:
                eviction_key: _CredentialCacheKey | None = None
                for existing_key, existing_state in self._states.items():
                    if existing_state.leases == 0:
                        eviction_key = existing_key
                        break
                if eviction_key is None:
                    raise ServiceCredentialUnavailable("service credential cache is at capacity")
                del self._states[eviction_key]

            state = _OrganizationCredentialState(leases=1)
            self._states[cache_key] = state
            return state

    def _release_state(self, cache_key: _CredentialCacheKey, state: _OrganizationCredentialState) -> None:
        with self._states_lock:
            if self._states.get(cache_key) is state:
                state.leases -= 1


_service_credential_cache = ServiceCredentialCache()


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
    credential_cache: ServiceCredentialCache | None = None,
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
