from __future__ import annotations

import json
import shutil
import logging
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SETUP_GUIDE = "docs/internal/sandboxes-setup-guide.md"

FUNNEL_PUBLIC_PORTS: tuple[int, ...] = (443, 8443, 10000)
"""The only public ports Tailscale Funnel will serve — the daemon rejects any
other. Three is exactly enough for the harness's Django, LLM gateway, and MCP
callbacks; each requested service is assigned one in the order the caller lists
them."""


class TailscaleFunnelError(RuntimeError):
    """Tailscale Funnel could not expose the host services for the eval run."""


@dataclass(frozen=True, kw_only=True)
class _Assignment:
    """A service's local port and the public Funnel port it is served on. Both are
    ports, so keyword-only construction keeps the two from being swapped."""

    local_port: int
    public_port: int


def _run_tailscale(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)


def tailscale_status() -> dict[str, Any] | None:
    """Return the parsed ``tailscale status --json`` payload, or ``None`` when the
    binary is missing, the daemon is unreachable, or the output is unparseable."""
    try:
        result = _run_tailscale(["status", "--json"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def funnel_preflight_error() -> str | None:
    """Return a one-line-fixable message if Tailscale Funnel can't be used yet, else None.

    Checked before any infrastructure boots so a missing binary or an unauthenticated
    node fails fast, rather than surfacing only when the first sandbox can't reach the host.
    Funnel enablement (tailnet ACLs, HTTPS certs) is left to ``TailscaleFunnel.start``,
    which surfaces the daemon's own actionable error immediately.
    """
    if shutil.which("tailscale") is None:
        return (
            "`tailscale` not found on PATH. Modal sandboxes run outside this host, so the "
            "Django API, LLM gateway, and MCP server must be publicly reachable via Tailscale Funnel. "
            f"See {SETUP_GUIDE}."
        )
    status = tailscale_status()
    if status is None:
        return f"Could not reach the Tailscale daemon. Start tailscaled and run `tailscale up`. See {SETUP_GUIDE}."
    state = status.get("BackendState")
    if state != "Running":
        return (
            f"Tailscale is not connected (backend state: {state or 'unknown'}). "
            f"Run `tailscale up` and sign in. See {SETUP_GUIDE}."
        )
    return None


def _public_url(host: str, public_port: int) -> str:
    # Funnel always terminates TLS. Port 443 is implicit in an https URL; the other
    # two Funnel ports must be spelled out.
    if public_port == 443:
        return f"https://{host}"
    return f"https://{host}:{public_port}"


def _configured_public_ports() -> set[int]:
    """Public ports that already carry Tailscale Serve/Funnel config, parsed from
    ``tailscale serve status --json``. Empty when nothing is configured or the
    status can't be read — so a collision is only ever reported on evidence, never
    guessed."""
    try:
        result = _run_tailscale(["serve", "status", "--json"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, dict):
        return set()
    ports: set[int] = set()
    # Web/AllowFunnel keys are "host:port"; TCP keys are a bare port.
    for section in ("Web", "AllowFunnel", "TCP"):
        entries = payload.get(section)
        if not isinstance(entries, dict):
            continue
        for key in entries:
            try:
                ports.add(int(str(key).rsplit(":", 1)[-1]))
            except ValueError:
                continue
    return ports


class TailscaleFunnel:
    """Modal-only Tailscale Funnel lifecycle: publicly exposes the host services a
    remote Modal sandbox must reach (Django API, LLM gateway, MCP server).

    Each service is served over HTTPS on one of Tailscale's three permitted public
    ports and is reachable by anyone on the internet who learns the URL, so the
    mappings exist only for the duration of the run and are turned off on ``stop``.
    Unlike a tunnel agent that drops its tunnels when killed, ``--bg`` Funnel config
    lives in tailscaled and outlives this process, so teardown must run — the caller
    registers ``stop`` on its cleanup stack.
    """

    def __init__(self, ports: dict[str, int]) -> None:
        if len(ports) > len(FUNNEL_PUBLIC_PORTS):
            raise TailscaleFunnelError(
                f"Tailscale Funnel exposes at most {len(FUNNEL_PUBLIC_PORTS)} public ports "
                f"({', '.join(map(str, FUNNEL_PUBLIC_PORTS))}), but {len(ports)} services were requested."
            )
        self._assignments: dict[str, _Assignment] = {
            name: _Assignment(local_port=local_port, public_port=public_port)
            for (name, local_port), public_port in zip(ports.items(), FUNNEL_PUBLIC_PORTS)
        }
        self._public_urls: dict[str, str] = {}
        self._enabled_ports: list[int] = []

    def start(self) -> None:
        host = self._resolve_public_host()
        # Refuse rather than clobber: Funnel's three ports are all we have, so if the
        # developer already serves one, overwriting it (and turning it off on teardown)
        # would silently take down their service. Bail with a fix instead.
        occupied = _configured_public_ports()
        conflicts = sorted(a.public_port for a in self._assignments.values() if a.public_port in occupied)
        if conflicts:
            raise TailscaleFunnelError(
                self._failure_message(
                    f"Tailscale Serve/Funnel is already configured on port(s) {', '.join(map(str, conflicts))}. "
                    f"Free them (e.g. `tailscale funnel --https {conflicts[0]} off`) before running Modal evals."
                )
            )
        for name, assignment in self._assignments.items():
            self._enable_funnel(assignment.public_port, assignment.local_port)
            self._enabled_ports.append(assignment.public_port)
            self._public_urls[name] = _public_url(host, assignment.public_port)
        logger.info("Tailscale Funnel ready: %s", self._public_urls)

    def url_for(self, name: str) -> str:
        return self._public_urls[name].rstrip("/")

    def stop(self) -> None:
        # Turn off only the ports this run enabled — start() refused any port that was
        # already configured, so these are ours to reclaim. A port whose `off` fails
        # stays public, so keep it tracked and log loudly: the caller registers stop()
        # on its cleanup stack (and atexit), so a later invocation retries it.
        still_public: list[int] = []
        for port in self._enabled_ports:
            try:
                result = _run_tailscale(["funnel", "--https", str(port), "off"], timeout=15)
            except Exception:
                logger.warning(
                    "Failed to turn off Tailscale Funnel on port %s; it is still public", port, exc_info=True
                )
                still_public.append(port)
                continue
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                logger.error(
                    "Tailscale Funnel port %s is still public: `tailscale funnel --https %s off` failed: %s",
                    port,
                    port,
                    detail,
                )
                still_public.append(port)
        self._enabled_ports = still_public
        if not still_public:
            self._public_urls = {}

    def _resolve_public_host(self) -> str:
        status = tailscale_status()
        if status is None:
            raise TailscaleFunnelError(self._failure_message("could not read `tailscale status --json`."))
        self_node = status.get("Self")
        dns_name = self_node.get("DNSName") if isinstance(self_node, dict) else None
        if not isinstance(dns_name, str) or not dns_name:
            raise TailscaleFunnelError(
                self._failure_message("`tailscale status` did not report this node's MagicDNS name.")
            )
        return dns_name.rstrip(".")

    def _enable_funnel(self, public_port: int, local_port: int) -> None:
        # `--bg` registers the mapping and returns; a bare local port target proxies
        # to http://127.0.0.1:<local_port>, matching each plain-HTTP host service.
        try:
            result = _run_tailscale(["funnel", "--bg", f"--https={public_port}", str(local_port)], timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            self.stop()
            raise TailscaleFunnelError(self._failure_message(str(e))) from e
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            self.stop()
            raise TailscaleFunnelError(self._failure_message(detail))

    def _failure_message(self, detail: str) -> str:
        return (
            f"{detail}\n"
            "Tailscale Funnel could not serve the Django, LLM gateway, and MCP services. "
            "Make sure tailscaled is running and this node is logged in (`tailscale up`), that Funnel "
            "is enabled for the tailnet and this node in the admin console's ACLs, and that HTTPS "
            f"certificates are enabled for the tailnet. See {SETUP_GUIDE}."
        )
