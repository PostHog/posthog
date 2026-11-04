from __future__ import annotations

import re
from collections.abc import Collection, Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from django.conf import settings

import requests
import structlog
from requests.auth import HTTPBasicAuth
from requests.utils import resolve_proxies

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, get_query_tags
from posthog.ph_client import feature_enabled_or_false

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTrinoConnection,
    ManagedWarehouseTrinoConnectionUnavailable,
    ServiceCredential,
    ServiceCredentialTrinoConnect,
    ServiceCredentialUnavailable,
)
from products.managed_warehouse.backend.facade.feature_flags import MANAGED_WAREHOUSE_TRINO_CANARY_FLAG
from products.managed_warehouse.backend.service_credentials import mint_service_credential, renew_service_credential

if TYPE_CHECKING:
    from trino.dbapi import Connection

LOGGER = structlog.get_logger(__name__)

_CREDENTIAL_REFRESH_MARGIN = timedelta(minutes=2)
_CREDENTIAL_REQUEST_TIMEOUT_SECONDS = 10
_HOSTED_SERVICE_DOMAINS = frozenset({"dw.us.postwh.com", "dw.eu.postwh.com", "dw.dev.postwh.com"})
_AUTOMATED_LIMIT_CONTEXTS = frozenset({LimitContext.EXPORT, LimitContext.SQL_ALERT, LimitContext.POSTHOG_AI})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canary_domain() -> str:
    return settings.MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN.strip().lower().strip(".")


def _require_canary_domain() -> str:
    domain = _canary_domain()
    if not domain:
        raise ManagedWarehouseTrinoConnectionUnavailable("The Trino canary domain is not configured")
    return domain


def _is_single_label_under(host: str, domains: Collection[str]) -> bool:
    label, _, domain = host.lower().removesuffix(".").partition(".")
    return domain in domains and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is not None


def _is_hosted_service_target(host: str) -> bool:
    # Tenant endpoints are trusted only when issued by the control plane, never from external-source configuration.
    canary_domain = _canary_domain()
    # An empty canary domain must stay out of the set, because a host without a domain would match it.
    return _is_single_label_under(host, _HOSTED_SERVICE_DOMAINS | ({canary_domain} if canary_domain else set()))


def _with_canary_host(connection: ManagedWarehouseTrinoConnection, canary: bool) -> ManagedWarehouseTrinoConnection:
    if not canary:
        return connection
    domain = _require_canary_domain()
    # Only a host that the control plane issued under a normal domain has a canary equivalent.
    if not _is_single_label_under(connection.host, _HOSTED_SERVICE_DOMAINS):
        raise ManagedWarehouseTrinoConnectionUnavailable("The Trino canary route needs a hosted warehouse host")
    # The canary host keeps the database label of the minted host, so the same service credential applies.
    label = connection.host.lower().removesuffix(".").partition(".")[0]
    return replace(connection, host=f"{label}.{domain}")


def _is_automated_run(limit_context: LimitContext | None) -> bool:
    # The alert and warming code sets these tags before it calls any query runner, so they are visible in every
    # layer. Exports and subscriptions run as their creator and carry no tag, so the limit context identifies them.
    tags = get_query_tags()
    return (
        limit_context in _AUTOMATED_LIMIT_CONTEXTS
        or tags.alert_config_id is not None
        or tags.feature in (Feature.ALERTING, Feature.CACHE_WARMUP)
        or (tags.trigger or "").startswith("warming")
    )


def use_trino_canary(
    distinct_id: str | None, organization_id: str, *, limit_context: LimitContext | None = None
) -> bool:
    """Whether an interactive run for this user connects through the canary hostname.

    The cheap checks come first, so the remote flag evaluation runs only for a user who could reach the canary.
    A caller decides once per query and reuses the result, because each call evaluates the flag again.
    """
    if not _canary_domain() or not distinct_id or _is_automated_run(limit_context):
        return False
    try:
        return feature_enabled_or_false(
            MANAGED_WAREHOUSE_TRINO_CANARY_FLAG,
            distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        LOGGER.warning("Failed to evaluate the Trino canary feature flag", organization_id=organization_id)
        return False


def _connection_from_credential(credential: ServiceCredential) -> ManagedWarehouseTrinoConnection:
    target = credential.trino_connect
    if (
        target is None
        or not re.fullmatch(r"svc_[0-9a-f]{24}", credential.credential_id)
        or not credential.credential_secret
        or credential.expires_at.tzinfo is None
        or credential.expires_at <= _utcnow() + _CREDENTIAL_REFRESH_MARGIN
        or not (target.username == credential.credential_id or target.username.endswith("." + credential.credential_id))
    ):
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The control plane did not return a usable Trino service credential. Check Trino service authentication readiness."
        )
    return ManagedWarehouseTrinoConnection(
        host=target.host,
        port=target.port,
        catalog=target.catalog,
        username=target.username,
        password=credential.credential_secret,
        credential_id=credential.credential_id,
        expires_at=credential.expires_at,
    )


def resolve_managed_warehouse_trino_connection(
    organization_id: str, *, principal: str = "posthog:trino"
) -> ManagedWarehouseTrinoConnection:
    try:
        credential = mint_service_credential(
            organization_id,
            principal=principal,
            timeout_seconds=_CREDENTIAL_REQUEST_TIMEOUT_SECONDS,
        )
        return _connection_from_credential(credential)
    except ServiceCredentialUnavailable as error:
        raise ManagedWarehouseTrinoConnectionUnavailable("Could not mint a Trino service credential") from error


class _TrinoServiceSession(requests.Session):
    def __init__(
        self, organization_id: str, connection: ManagedWarehouseTrinoConnection, *, canary: bool = False
    ) -> None:
        super().__init__()
        self._organization_id = organization_id
        self._connection = connection
        self._canary = canary
        self._lock = Lock()
        # Defer authentication until send so queued requests also check credential expiry.
        self.auth = self._defer_authentication

    @staticmethod
    def _defer_authentication(request: requests.PreparedRequest) -> requests.PreparedRequest:
        return request

    def send(
        self,
        request: requests.PreparedRequest,
        *,
        stream: bool | None = None,
        verify: bool | str | None = None,
        proxies: MutableMapping[str, str] | None = None,
        cert: str | tuple[str, str] | None = None,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        allow_redirects: bool = True,
        **kwargs: object,
    ) -> requests.Response:
        if kwargs:
            raise TypeError("Unsupported Trino HTTP transport options")
        # Serialize renewal so polling and cancellation share one grant expiry.
        with self._lock:
            connection = self._connection
            destination = urlsplit(request.url or "")
            if (
                destination.scheme != "https"
                or (destination.hostname or "").lower().removesuffix(".") != connection.host.lower().removesuffix(".")
                or (destination.port or 443) != connection.port
                or destination.username is not None
                or destination.password is not None
            ):
                raise ManagedWarehouseTrinoConnectionUnavailable(
                    "Trino returned a different service credential destination"
                )
            if connection.expires_at <= _utcnow() + _CREDENTIAL_REFRESH_MARGIN:
                try:
                    credential = renew_service_credential(
                        self._organization_id,
                        connection.credential_id,
                        credential_secret=connection.password,
                        timeout_seconds=_CREDENTIAL_REQUEST_TIMEOUT_SECONDS,
                    )
                    reused_target = credential.trino_connect is None
                    if reused_target:
                        # Readiness can hide dial targets during renewal without invalidating an existing query's grant.
                        credential = replace(
                            credential,
                            trino_connect=ServiceCredentialTrinoConnect(
                                host=connection.host,
                                port=connection.port,
                                catalog=connection.catalog,
                                username=connection.username,
                                http_scheme="https",
                            ),
                        )
                    refreshed = _connection_from_credential(credential)
                except ServiceCredentialUnavailable as error:
                    raise ManagedWarehouseTrinoConnectionUnavailable(
                        "Could not renew the Trino service credential"
                    ) from error
                # The control plane returns the normal host again. A reused target already holds the canary host.
                if not reused_target:
                    refreshed = _with_canary_host(refreshed, self._canary)
                if (
                    refreshed.credential_id != connection.credential_id
                    or refreshed.host != connection.host
                    or refreshed.port != connection.port
                    or refreshed.catalog != connection.catalog
                    or refreshed.username != connection.username
                ):
                    raise ManagedWarehouseTrinoConnectionUnavailable(
                        "Trino service credential target changed during the query"
                    )
                connection = self._connection = refreshed
        HTTPBasicAuth(connection.username, connection.password)(request)
        response = super().send(
            request,
            stream=self.stream if stream is None else stream,
            verify=self.verify if verify is None else verify,
            proxies=resolve_proxies(request, self.proxies, self.trust_env) if proxies is None else proxies,
            cert=self.cert if cert is None else cert,
            timeout=timeout,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            response.close()
            raise ManagedWarehouseTrinoConnectionUnavailable("Trino redirected a service-authenticated request")
        return response


@contextmanager
def connect_managed_warehouse_trino(
    organization_id: str, *, principal: str = "posthog:trino", canary: bool = False
) -> Iterator[Connection]:
    from trino.dbapi import connect  # noqa: PLC0415 -- keeps the optional driver off startup paths

    if canary:
        _require_canary_domain()
    config = _with_canary_host(resolve_managed_warehouse_trino_connection(organization_id, principal=principal), canary)
    with _TrinoServiceSession(organization_id, config, canary=canary) as http_session:
        if _is_hosted_service_target(config.host) and config.port == 443:
            http_session.trust_env = False
        connection = connect(
            host=config.host,
            port=config.port,
            user=config.username,
            catalog=config.catalog,
            http_scheme="https",
            request_timeout=60,
            verify=True,
            http_session=http_session,
        )
        try:
            yield connection
        finally:
            connection.close()
