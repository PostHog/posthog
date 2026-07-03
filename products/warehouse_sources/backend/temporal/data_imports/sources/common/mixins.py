import time
import socket
from collections.abc import Callable, Generator
from contextlib import _GeneratorContextManager, contextmanager
from typing import Any

from django.db import OperationalError, close_old_connections

import structlog

from posthog.cloud_utils import is_cloud
from posthog.models.integration import Integration
from posthog.utils import get_instance_region

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel
from products.warehouse_sources.backend.models.util import _is_safe_public_ip

logger = structlog.get_logger(__name__)

_INTERNAL_IP_ERROR = "Hosts with internal IP addresses are not allowed"
_DNS_FAILURE_ERROR = "Host could not be resolved"


def _is_host_safe(host: str, team_id: int) -> tuple[bool, str | None]:
    """Validate that a host is not an internal/private IP address.

    Only enforced on cloud deployments — self-hosted instances are allowed
    to connect to any host.

    Resolves hostnames via DNS and checks all resolved IPs against
    _is_safe_public_ip to block private, loopback, link-local, multicast,
    reserved, and IPv6-mapped internal addresses.

    team whitelist: team_id 2 in US, team_id 1 in EU are allowed
    to use internal IPs.
    """

    def _log(decision: str, stage: str, reason: str | None, resolved_ips: list[str] | None = None) -> None:
        if decision == "block":
            log_fn = logger.warning  # SSRF attempt — always logged
        elif stage in ("not_cloud", "e2e"):
            log_fn = logger.debug  # never fires on cloud / spammy on self-hosted
        else:
            log_fn = logger.info

        log_fn(
            "data_imports.host_check",
            host=host,
            team_id=team_id,
            decision=decision,
            stage=stage,
            reason=reason,
            resolved_ips=resolved_ips,
        )

    if not is_cloud():
        _log("allow", "not_cloud", None)
        return True, None

    region = get_instance_region()
    if region == "E2E":
        _log("allow", "e2e", None)
        return True, None

    if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
        _log("allow", "team_allowlist", None)
        return True, None

    normalized = host.lower().strip().rstrip(".")

    # PostHog-managed DuckLake hosts resolve to internal IPs but are safe.
    if normalized.endswith(".postwh.com"):
        _log("allow", "postwh_managed", None)
        return True, None

    if normalized in {"localhost"}:
        _log("block", "localhost", _INTERNAL_IP_ERROR)
        return False, _INTERNAL_IP_ERROR

    try:
        if not _is_safe_public_ip(host):
            _log("block", "literal_ip", _INTERNAL_IP_ERROR)
            return False, _INTERNAL_IP_ERROR
    except ValueError:
        pass

    try:
        addrinfo = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        resolved_ips = [str(sockaddr[0]) for *_meta, sockaddr in addrinfo]
        for resolved_ip in resolved_ips:
            if not _is_safe_public_ip(resolved_ip):
                _log("block", "resolved_ip", _INTERNAL_IP_ERROR, resolved_ips)
                return False, _INTERNAL_IP_ERROR
    except socket.gaierror:
        _log("block", "dns_failure", _DNS_FAILURE_ERROR)
        return (
            False,
            f"Couldn't resolve the host '{host}'. Check that it's spelled correctly and reachable from the public internet.",
        )

    _log("allow", "resolved_ip", None, resolved_ips)
    return True, None


def log_connection_open(
    *,
    db_host: str,
    db_port: int | str | None = None,
    via: str = "direct",
    ssh_host: str | None = None,
    ssh_port: int | str | None = None,
    team_id: int | None = None,
    **fields: Any,
) -> None:
    """Emit `data_imports.connection_open` — one line per outbound connection to a customer host."""
    event_fields: dict[str, Any] = {"db_host": db_host, "via": via, **fields}
    for key, value in (("db_port", db_port), ("ssh_host", ssh_host), ("ssh_port", ssh_port), ("team_id", team_id)):
        if value is not None:
            event_fields[key] = value
    logger.info("data_imports.connection_open", **event_fields)


@contextmanager
def _logged_connection(config, team_id: int | None) -> Generator[None]:
    ssh = getattr(config, "ssh_tunnel", None)
    if ssh is not None and ssh.enabled:
        via, ssh_host, ssh_port = "ssh_tunnel", ssh.host, ssh.port
    else:
        via, ssh_host, ssh_port = "direct", None, None
    log_connection_open(
        db_host=config.host,
        db_port=config.port,
        via=via,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        team_id=team_id,
    )
    try:
        yield
    except Exception as e:
        # Coarse by design: the block spans the whole connection lifetime, so this also
        # catches mid-sync errors — error_type disambiguates, and a down tunnel retrying
        # is exactly the pattern this exists to make visible.
        logger.warning(
            "data_imports.connection_error",
            db_host=config.host,
            via=via,
            error_type=type(e).__name__,
            error=str(e)[:200],
            **({"team_id": team_id} if team_id is not None else {}),
        )
        raise


@contextmanager
def open_ssh_tunnel(config, team_id: int | None = None) -> Generator[tuple[str, int]]:
    """Yield `(host, port)` for a database connection, going through an SSH tunnel if configured."""
    with _logged_connection(config, team_id):
        if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
            ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

            with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
                if tunnel is None:
                    raise Exception("Can't open tunnel to SSH server")

                yield tunnel.local_bind_host, tunnel.local_bind_port
        else:
            yield config.host, config.port


def make_ssh_tunnel_factory(
    config, team_id: int | None = None
) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
    """Return a zero-arg factory that opens a fresh `open_ssh_tunnel(config)` context each call.

    The dlt pipeline factories accept a tunnel-factory callable so the tunnel can be
    (re)opened inside the pipeline process.
    """
    if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

        @contextmanager
        def with_ssh_func():
            with _logged_connection(config, team_id):
                with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
                    if tunnel is None:
                        raise Exception("Can't open tunnel to SSH server")
                    yield tunnel.local_bind_host, tunnel.local_bind_port

        return with_ssh_func

    @contextmanager
    def without_ssh_func():
        with _logged_connection(config, team_id):
            yield config.host, config.port

    return without_ssh_func


class SSHTunnelMixin:
    """Mixin for sources that support SSH tunnels"""

    def with_ssh_tunnel(self, config, team_id: int | None = None) -> _GeneratorContextManager[tuple[str, int]]:
        return open_ssh_tunnel(config, team_id)

    def make_ssh_tunnel_func(
        self, config, team_id: int | None = None
    ) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
        return make_ssh_tunnel_factory(config, team_id)

    def ssh_tunnel_is_valid(self, config, team_id: int) -> tuple[bool, str | None]:
        if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
            if config.ssh_tunnel.host:
                is_host_valid, host_errors = _is_host_safe(config.ssh_tunnel.host, team_id)
                if not is_host_valid:
                    return False, f"SSH tunnel host not allowed: {host_errors}"

            ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)
            is_auth_valid, auth_errors = ssh_tunnel.is_auth_valid()
            if not is_auth_valid:
                return is_auth_valid, auth_errors

            is_port_valid, port_errors = ssh_tunnel.has_valid_port()
            if not is_port_valid:
                return is_port_valid, port_errors

        return True, None


_MAX_INTEGRATION_FETCH_ATTEMPTS = 4


def _integration_fetch_backoff_sleep(attempt: int) -> None:
    """Sleep before the next integration-fetch retry: linear growth capped at 30s (2s, 4s, 6s, ...)."""
    time.sleep(min(2 * attempt, 30))


class OAuthMixin:
    """Mixin for OAuth-based sources"""

    def get_oauth_integration(self, integration_id: int, team_id: int) -> Integration:
        """Get OAuth integration from integration ID.

        Temporal activities run in a long-lived worker outside Django's request cycle, so a pooled
        Postgres connection can be closed server-side while idle, or the connection pooler can
        reject the query with a wait timeout when the pool is saturated. Both surface as a transient
        ``OperationalError`` that clears on a healthy connection, so this idempotent lookup is
        retried with backoff before failing the whole import on a momentary blip. A failed query
        marks its connection unusable, so ``close_old_connections()`` evicts it between attempts and
        the next attempt runs on a fresh one; the sleep lets a saturated pool drain. A genuinely
        missing integration is surfaced as the stable, non-retryable ``ValueError`` and is not
        retried.
        """
        if not integration_id:
            raise ValueError(f"Missing integration ID")

        attempt = 0
        while True:
            try:
                return Integration.objects.get(id=integration_id, team_id=team_id)
            except Integration.DoesNotExist:
                raise ValueError(f"Integration not found: {integration_id}") from None
            except OperationalError:
                attempt += 1
                if attempt >= _MAX_INTEGRATION_FETCH_ATTEMPTS:
                    raise
                close_old_connections()
                _integration_fetch_backoff_sleep(attempt)


class ValidateDatabaseHostMixin:
    """Mixin for database-based sources to validate connection host"""

    def is_database_host_valid(
        self, host: str, team_id: int, using_ssh_tunnel: bool = False
    ) -> tuple[bool, str | None]:
        if using_ssh_tunnel:
            return True, None

        return _is_host_safe(host, team_id)
