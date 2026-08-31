import time
import socket
import ipaddress
import dataclasses
from collections.abc import Callable, Generator
from contextlib import _GeneratorContextManager, contextmanager
from typing import Any

from django.db import OperationalError, close_old_connections

import structlog

from posthog.cloud_utils import is_cloud
from posthog.models.integration import Integration
from posthog.psycopg_helpers import prefer_routable_addresses
from posthog.utils import get_instance_region

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel
from products.warehouse_sources.backend.models.util import _is_safe_public_ip
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
)

logger = structlog.get_logger(__name__)

_INTERNAL_IP_ERROR = (
    "This host points to an internal or private IP address, which PostHog can't reach. "
    "Use a host that's reachable from the public internet."
)
_DNS_FAILURE_ERROR = "Host could not be resolved"


def is_team_allowlisted_for_internal_hosts(team_id: int) -> bool:
    """Whether this team may point warehouse sources at PostHog-internal hosts.

    Only our own internal analytics projects: team 2 in US, team 1 in EU.
    Gates both the SSRF host check and the egress-proxy bypass for direct
    connections to internal databases.
    """
    region = get_instance_region()
    return (region == "US" and team_id == 2) or (region == "EU" and team_id == 1)


@dataclasses.dataclass(frozen=True, kw_only=True)
class HostResolution:
    """The outcome of `resolve_safe_host`.

    `connect_host` is None exactly when the host was rejected, in which case `error` carries
    the user-facing reason.
    """

    connect_host: str | None
    error: str | None


def _is_host_safe(host: str, team_id: int) -> tuple[bool, str | None]:
    """Whether a host is safe to connect to. See `resolve_safe_host` for the policy.

    Callers that go on to open the connection themselves should use `resolve_safe_host` and
    connect to the address it returns, so that the address checked is the address used.
    """
    resolution = resolve_safe_host(host, team_id)
    return resolution.connect_host is not None, resolution.error


def resolve_safe_host(host: str, team_id: int | None) -> HostResolution:
    """Resolve a host to the address a connection should actually be made to.

    Only enforced on cloud deployments — self-hosted instances are allowed
    to connect to any host.

    Resolves hostnames via DNS and checks all resolved IPs against
    _is_safe_public_ip to block private, loopback, link-local, multicast,
    reserved, and IPv6-mapped internal addresses.

    team whitelist: team_id 2 in US, team_id 1 in EU are allowed
    to use internal IPs.

    When the check applies, `connect_host` is one of the validated IPs rather than the
    hostname that was passed in, and callers must connect to it. Handing the hostname to a
    connection library resolves it a second time, and a record with a short TTL can answer
    with a public address for this check and a private one for the connect, which defeats the
    check entirely. When the check is skipped there is no resolution to pin, so the hostname
    comes back unchanged.
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

    def _allow_unpinned(stage: str) -> HostResolution:
        _log("allow", stage, None)
        return HostResolution(connect_host=host, error=None)

    def _block(stage: str, error: str, resolved_ips: list[str] | None = None) -> HostResolution:
        _log("block", stage, error, resolved_ips)
        return HostResolution(connect_host=None, error=error)

    if not is_cloud():
        return _allow_unpinned("not_cloud")

    region = get_instance_region()
    if region == "E2E":
        return _allow_unpinned("e2e")

    if team_id is not None and is_team_allowlisted_for_internal_hosts(team_id):
        return _allow_unpinned("team_allowlist")

    normalized = host.lower().strip().rstrip(".")

    # PostHog-managed DuckLake hosts resolve to internal IPs but are safe.
    if normalized.endswith(".postwh.com"):
        return _allow_unpinned("postwh_managed")

    if normalized in {"localhost"}:
        return _block("localhost", _INTERNAL_IP_ERROR)

    try:
        if not _is_safe_public_ip(host):
            return _block("literal_ip", _INTERNAL_IP_ERROR)
    except ValueError:
        pass

    dns_failure_error = (
        f"Couldn't resolve the host '{host}'. Check that it's spelled correctly and reachable from the public internet."
    )
    try:
        addrinfo = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        resolved_ips = [str(sockaddr[0]) for *_meta, sockaddr in addrinfo]
    except (socket.gaierror, UnicodeError):
        # getaddrinfo IDNA-encodes the host, so a malformed hostname (e.g. a DNS label over 63
        # bytes) raises UnicodeError ("label too long") instead of gaierror. Either way the host
        # can't be resolved — return the actionable message rather than crashing.
        _log("block", "dns_failure", _DNS_FAILURE_ERROR)
        return HostResolution(connect_host=None, error=dns_failure_error)

    for resolved_ip in resolved_ips:
        if not _is_safe_public_ip(resolved_ip):
            return _block("resolved_ip", _INTERNAL_IP_ERROR, resolved_ips)

    if not resolved_ips:
        _log("block", "dns_failure", _DNS_FAILURE_ERROR)
        return HostResolution(connect_host=None, error=dns_failure_error)

    _log("allow", "resolved_ip", None, resolved_ips)
    # getaddrinfo returns addresses in the order the resolver prefers, which is the order a
    # connect would try them in. Pinning the first one gives up that fallback: if it is down,
    # nothing tries the next. Every address in the list passed the check above, so this costs
    # availability on multi-address hosts, not safety.
    #
    # That order is IPv6-first for a dual-stack host (RFC 6724), so on an IPv4-only worker the
    # pinned address is one nothing can route to and the connection can never succeed. Order by
    # what this host can actually reach before pinning.
    return HostResolution(connect_host=prefer_routable_addresses(resolved_ips)[0], error=None)


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


def _enabled_ssh_tunnel(config) -> Any | None:
    """Return the config's SSH tunnel settings when enabled, else None.

    The single predicate for both the connection log and the tunnel/direct branch,
    so the logged `via` can never disagree with the path actually taken.
    """
    ssh = getattr(config, "ssh_tunnel", None)
    return ssh if ssh and ssh.enabled else None


@contextmanager
def _logged_connection(config, team_id: int | None) -> Generator[None]:
    ssh = _enabled_ssh_tunnel(config)
    if ssh is not None:
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
            **({"db_port": config.port} if config.port is not None else {}),
            **({"team_id": team_id} if team_id is not None else {}),
        )
        raise


def _require_loopback(host: str) -> str:
    """Refuse to treat a non-loopback address as a tunnel bind.

    ClickHouse skips the egress proxy for tunneled connections on the strength of the tunnel
    branch only ever yielding its own loopback bind address (`SSHTunnel.get_tunnel` pins
    `local_bind_address` to 127.0.0.1). That invariant lives in a different file from the
    bypass, so enforce it where the address is produced: if a future change makes this branch
    yield anything else — a fallback to the configured host, a non-loopback bind — the proxy
    bypass would silently extend to it, and this raises instead.
    """
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise Exception(f"SSH tunnel bound to non-loopback address {host!r}; refusing to use it")
    return host


def _pinned_ssh_host(ssh_config, team_id: int | None) -> str:
    """Resolve the SSH host and return the address to open the tunnel to.

    Enforced here, at the connect, rather than left to `ssh_tunnel_is_valid` at the API layer.
    That validation runs when a source is created, updated, or directly queried, but the sync
    path goes from the stored config straight to the tunnel, so a host that resolved to a
    public address at setup is never re-checked on any later scheduled run. The SSH hop is a
    raw socket that no egress proxy sees, which makes this check the only thing in its path.
    """
    resolution = resolve_safe_host(ssh_config.host, team_id)
    if resolution.connect_host is None:
        raise Exception(f"SSH tunnel host not allowed: {resolution.error}")
    return resolution.connect_host


@contextmanager
def open_ssh_tunnel(config, team_id: int | None = None) -> Generator[tuple[str, int]]:
    """Yield `(host, port)` for a database connection, going through an SSH tunnel if configured."""
    with _logged_connection(config, team_id):
        ssh_config = _enabled_ssh_tunnel(config)
        if ssh_config is not None:
            ssh_tunnel = SSHTunnel.from_config(ssh_config)

            with ssh_tunnel.get_tunnel(
                config.host, config.port, ssh_host=_pinned_ssh_host(ssh_config, team_id)
            ) as tunnel:
                if tunnel is None:
                    raise Exception("Can't open tunnel to SSH server")

                yield _require_loopback(tunnel.local_bind_host), tunnel.local_bind_port
        else:
            yield config.host, config.port


def make_ssh_tunnel_factory(
    config, team_id: int | None = None
) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
    """Return a zero-arg factory that opens a fresh `open_ssh_tunnel(config)` context each call.

    The dlt pipeline factories accept a tunnel-factory callable so the tunnel can be
    (re)opened inside the pipeline process.
    """
    ssh_config = _enabled_ssh_tunnel(config)
    if ssh_config is not None:
        ssh_tunnel = SSHTunnel.from_config(ssh_config)

        @contextmanager
        def with_ssh_func():
            with _logged_connection(config, team_id):
                # Resolved per reopen, not once when the factory is built, so a long-running
                # sync that reopens the tunnel re-checks the host each time.
                with ssh_tunnel.get_tunnel(
                    config.host, config.port, ssh_host=_pinned_ssh_host(ssh_config, team_id)
                ) as tunnel:
                    if tunnel is None:
                        raise Exception("Can't open tunnel to SSH server")
                    yield _require_loopback(tunnel.local_bind_host), tunnel.local_bind_port

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

    def ssh_tunnel_enabled(self, config) -> bool:
        """Whether the tunnel helpers above will tunnel rather than connect directly.

        For callers that need to know which branch was taken, because the `(host, port)` they
        receive means something different in each case: a tunnel yields our own local bind
        address, while a direct connection yields the user's configured host. Shares
        `_enabled_ssh_tunnel` with the branch itself so the two cannot drift apart.
        """
        return _enabled_ssh_tunnel(config) is not None

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

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # The account picker lives in the source: each OAuth source maps its provider's accounts onto
        # the shared IntegrationAccount contract, served by one generic endpoint. `search` is an optional
        # query for sources whose account/resource list is large enough to filter server-side (e.g. GitHub
        # repositories); small-list sources may ignore it and let the endpoint filter the result.
        raise NotImplementedError(f"{type(self).__name__} does not support listing OAuth accounts")


class ValidateDatabaseHostMixin:
    """Mixin for database-based sources to validate connection host"""

    def is_database_host_valid(
        self, host: str, team_id: int, using_ssh_tunnel: bool = False
    ) -> tuple[bool, str | None]:
        if using_ssh_tunnel:
            return True, None

        is_valid, error = _is_host_safe(host, team_id)
        if not is_valid and error == _INTERNAL_IP_ERROR:
            # Direct (non-tunneled) connection, so reaching a private database through a public
            # SSH bastion is a genuine workaround worth pointing at.
            return is_valid, f"{error} If your database isn't publicly reachable, connect through an SSH tunnel."
        return is_valid, error
