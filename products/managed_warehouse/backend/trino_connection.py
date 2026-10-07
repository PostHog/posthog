from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests
from requests.auth import HTTPBasicAuth
from requests.utils import resolve_proxies

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTrinoConnection,
    ManagedWarehouseTrinoConnectionUnavailable,
    ServiceCredential,
    ServiceCredentialTrinoConnect,
    ServiceCredentialUnavailable,
)
from products.managed_warehouse.backend.service_credentials import mint_service_credential, renew_service_credential

if TYPE_CHECKING:
    from trino.dbapi import Connection

_CREDENTIAL_REFRESH_MARGIN = timedelta(minutes=2)
_CREDENTIAL_REQUEST_TIMEOUT_SECONDS = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_hosted_service_target(host: str) -> bool:
    # Tenant endpoints are trusted only when issued by the control plane, never from external-source configuration.
    label, _, domain = host.lower().removesuffix(".").partition(".")
    return (
        domain in {"dw.us.postwh.com", "dw.dev.postwh.com"}
        and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is not None
    )


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
    def __init__(self, organization_id: str, connection: ManagedWarehouseTrinoConnection) -> None:
        super().__init__()
        self._organization_id = organization_id
        self._connection = connection
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
                    if credential.trino_connect is None:
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
def connect_managed_warehouse_trino(organization_id: str, *, principal: str = "posthog:trino") -> Iterator[Connection]:
    from trino.dbapi import connect  # noqa: PLC0415 -- keeps the optional driver off startup paths

    config = resolve_managed_warehouse_trino_connection(organization_id, principal=principal)
    with _TrinoServiceSession(organization_id, config) as http_session:
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
