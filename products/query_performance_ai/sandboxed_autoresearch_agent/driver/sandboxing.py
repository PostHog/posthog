"""In-sandbox setup: lockdown + pi-coding-agent toolchain provisioning.

Three concerns:

1. ``lockdown_network`` installs an iptables OUTPUT-DROP rule set that
   leaves only a narrow whitelist (loopback, the coordinator port at the
   Docker gateway, the Anthropic API host, and DNS to the configured
   resolvers). pi-coding-agent runs after this, so its egress is fully
   bounded.
2. ``ensure_pi_toolchain`` requires the PI_BASE image's pre-baked
   layout — ``pi`` on PATH and the extension at the expected location.
   Anything else fails fast: lockdown has already cut general egress, so
   even if we wanted to fall back to ``npm install`` / ``git clone`` we
   couldn't reach the registries, and we never want to run unpinned
   third-party code anyway.
3. ``prepare_pi_runtime`` patches the baked pi-ai bundle so it points
   at our ``ANTHROPIC_BASE_URL`` (when set) and patches pi-autoresearch's
   ``index.ts`` to preserve the campaign workspace dirs across pi's
   ``git clean -fd``.

The pi-ai gateway patch (`_patch_pi_ai_anthropic_baseurl`) is a no-op
for the production flow today (we forward only ``ANTHROPIC_API_KEY``;
the gateway-token path is intentionally disabled), but is kept so that
a future re-introduction of the LLM gateway can route through it again.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import urllib.parse
from pathlib import Path

from .runtime import PI_PLUGIN_DIR, CampaignError, atomic_write, log, run

# Layout the dedicated PI_BASE image bakes. `ensure_pi_toolchain` requires
# this exact path; the image build (Dockerfile.sandbox-pi) is the only place
# pi-coding-agent and pi-autoresearch are installed, both at their pinned
# versions/commits in the Dockerfile.
BAKED_PI_AUTORESEARCH_EXTENSION = Path("/root/.pi/agent/extensions/pi-autoresearch")


class LockdownFailed(CampaignError):
    pass


def _resolve_all(host: str, *, label: str) -> list[str]:
    """Return all IPv4 addresses ``host`` resolves to via ``getent hosts``.

    Raises :class:`LockdownFailed` if resolution fails. We call ``getent``
    rather than Python's resolver so the rule pinning matches what
    container-side connections will actually see.
    """
    try:
        out = subprocess.check_output(  # noqa: S603
            ["getent", "ahostsv4", host],
            text=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise LockdownFailed(f"could not resolve {label} host {host!r}: {e}") from e

    ips: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        ip = parts[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise LockdownFailed(f"{label} host {host!r} resolved to zero addresses")
    return ips


def _resolv_conf_nameservers(path: str = "/etc/resolv.conf") -> list[str]:
    """Read ``nameserver`` IPs from ``/etc/resolv.conf``.

    Falls back to Docker's embedded resolver (``127.0.0.11``) if no entries
    are found, so the lockdown still produces a reachable DNS path on a
    misconfigured container instead of dropping all DNS.
    """
    ips: list[str] = []
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver" and parts[1] not in ips:
                    ips.append(parts[1])
    except OSError:
        pass
    if not ips:
        ips.append("127.0.0.11")
    return ips


def lockdown_network(coordinator_url: str) -> None:
    """iptables OUTPUT-DROP except: loopback, the coordinator port at the
    gateway IP, and HTTPS to the Anthropic API (so pi-coding-agent can
    reach the LLM).

    Requires NET_ADMIN, `iptables` on PATH, and DNS resolution for
    ``host.docker.internal`` plus the Anthropic API host. Raises
    :class:`LockdownFailed` on any precondition failure or rule error.

    The Anthropic host is taken from ``ANTHROPIC_BASE_URL`` if set, else
    defaults to ``api.anthropic.com``. We resolve and pin its current
    IPs at lockdown time; if Anthropic rotates IPs during the campaign,
    new connections will fail with a clean network error rather than
    silently hanging.
    """
    parsed = urllib.parse.urlparse(coordinator_url)
    port = parsed.port
    if not port:
        raise LockdownFailed(
            f"coordinator URL has no explicit port: {coordinator_url!r} — refusing to lock down without a target"
        )
    # `host.docker.internal` resolves to the gateway via `--add-host`; resolve
    # it once so the rule pins the IP rather than depending on DNS later.
    gateway_ip = _resolve_all(parsed.hostname or "host.docker.internal", label="coordinator")[0]

    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or "https://api.anthropic.com"
    anthropic_parsed = urllib.parse.urlparse(anthropic_base)
    anthropic_host = anthropic_parsed.hostname
    if not anthropic_host:
        raise LockdownFailed(f"ANTHROPIC_BASE_URL has no host: {anthropic_base!r}")
    anthropic_port = anthropic_parsed.port or (443 if anthropic_parsed.scheme == "https" else 80)
    anthropic_ips = _resolve_all(anthropic_host, label="anthropic")

    # Allow rules go in OUTPUT slot 1..N (insertions push earlier ones down).
    allow_rules: list[list[str]] = []
    allow_rules.append(["-o", "lo", "-j", "ACCEPT"])
    allow_rules.append(["-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"])
    # Outbound DNS, pinned to the resolvers in /etc/resolv.conf (typically
    # Docker's embedded 127.0.0.11 plus whatever forwarders the daemon was
    # given). Without this pin, an unrestricted UDP/53 rule lets a process
    # DNS-tunnel data (e.g. ANTHROPIC_API_KEY) by encoding it as subdomains
    # toward an attacker-controlled resolver.
    for ip in _resolv_conf_nameservers():
        allow_rules.append(["-d", ip, "-p", "udp", "--dport", "53", "-j", "ACCEPT"])
    allow_rules.append(["-d", gateway_ip, "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])
    for ip in anthropic_ips:
        allow_rules.append(["-d", ip, "-p", "tcp", "--dport", str(anthropic_port), "-j", "ACCEPT"])

    # Apply DROP first so any partial-rule failure leaves the chain in the
    # safer "everything blocked" state rather than fail-open. In practice
    # any ``LockdownFailed`` here also kills this driver process — the
    # sandbox PID 1 exits, the container terminates, and the coordinator
    # destroys it — so the half-locked window is sub-second and pi never
    # gets to run. The ordering is defense-in-depth, not load-bearing.
    rules: list[list[str]] = [["iptables", "-P", "OUTPUT", "DROP"]]
    rules.extend(["iptables", "-I", "OUTPUT", "1", *r] for r in allow_rules)

    for argv in rules:
        try:
            subprocess.run(argv, check=True, text=True, capture_output=True, timeout=5)  # noqa: S603
        except FileNotFoundError as e:
            raise LockdownFailed("iptables binary missing in sandbox image") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            if "Operation not permitted" in stderr or "Permission denied" in stderr:
                raise LockdownFailed("iptables refused (NET_ADMIN not granted to this sandbox)") from e
            raise LockdownFailed(f"iptables rule failed ({argv[-1]}): {stderr}") from e

    # Drop IPv6 outbound entirely. Anthropic publishes AAAA records and
    # Node's HTTP client will prefer IPv6 if the resolver returns one; if
    # IPv6 routing in the container is broken (Docker default networks
    # disable IPv6) the connect fails fast and the agent reports
    # "Connection error" without falling back to IPv4. Forcing v6 to drop
    # via ip6tables makes happy-eyeballs fall through to v4 cleanly. We
    # don't whitelist any v6 destinations because our v4 whitelist is
    # already enough for pi to function.
    try:
        subprocess.run(  # noqa: S603
            ["ip6tables", "-P", "OUTPUT", "DROP"], check=True, text=True, capture_output=True, timeout=5
        )
    except FileNotFoundError:
        # ip6tables may be absent on stripped-down images; swallow because
        # IPv4 lockdown is the load-bearing part.
        pass
    except subprocess.CalledProcessError as e:
        # Don't fail the campaign on IPv6 lockdown failure either — same
        # rationale.
        log(f"warning: ip6tables OUTPUT DROP failed: {(e.stderr or '').strip()}")

    anthropic_ip_summary = ",".join(anthropic_ips)
    log(
        f"network locked down: coordinator {gateway_ip}:{port} + "
        f"{anthropic_host}:{anthropic_port} ([{anthropic_ip_summary}])"
    )

    # Diagnostic: prove the lockdown didn't accidentally break LLM access.
    # `curl -m 5` against the Anthropic API root will 401/404 (no API key in
    # the curl) but a non-zero TCP connection means the rules are right.
    try:
        diag = subprocess.run(  # noqa: S603
            [
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code} %{time_total}s",
                "-m",
                "5",
                f"https://{anthropic_host}/v1/models",
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )
        log(
            f"lockdown diagnostic: curl https://{anthropic_host}/v1/models → {diag.stdout.strip()} (rc={diag.returncode})"
        )
        if diag.returncode != 0:
            log(f"lockdown diagnostic stderr: {(diag.stderr or '').strip()[:500]}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"lockdown diagnostic skipped: {e}")


def ensure_pi_toolchain() -> None:
    """Require the pre-baked pi toolchain — fail fast if missing.

    PI_BASE (Dockerfile.sandbox-pi) is the only supported sandbox image
    for autoresearch; it bakes ``pi-coding-agent`` at a pinned version
    and ``pi-autoresearch`` at a pinned commit. We refuse to fall back
    to ``npm install`` / ``git clone`` because (a) lockdown has already
    cut general egress so it wouldn't work anyway, and (b) installing
    unpinned third-party code from inside a network-isolated sandbox is
    a pattern we explicitly never want.
    """
    pi_path = shutil.which("pi")
    if pi_path is None:
        raise CampaignError(
            "pi-coding-agent binary not found on PATH — sandbox image is wrong "
            "(expected PI_BASE / Dockerfile.sandbox-pi). Refusing to bootstrap "
            "an unpinned install at runtime."
        )
    if not BAKED_PI_AUTORESEARCH_EXTENSION.is_dir():
        raise CampaignError(
            f"pi-autoresearch extension not found at {BAKED_PI_AUTORESEARCH_EXTENSION} "
            "— sandbox image is wrong (expected PI_BASE / Dockerfile.sandbox-pi). "
            "Refusing to clone the upstream repo at runtime."
        )
    log(f"pi toolchain pre-installed (pi @ {pi_path}, extension at {BAKED_PI_AUTORESEARCH_EXTENSION})")


def prepare_pi_runtime() -> None:
    """Patch baked pi-ai / pi-autoresearch state and install the in-repo plugin."""
    _patch_pi_ai_anthropic_baseurl()
    _patch_pi_autoresearch_index_ts()

    plugin_dir = Path.home() / ".pi/packages/pi-clickhouse-autoresearch"
    if not plugin_dir.is_dir():
        log("installing local pi-clickhouse-autoresearch plugin")
        run(["pi", "install", str(PI_PLUGIN_DIR)])
    else:
        log("pi-clickhouse-autoresearch already installed")


def _patch_pi_autoresearch_index_ts() -> None:
    index_ts = BAKED_PI_AUTORESEARCH_EXTENSION / "index.ts"
    if not index_ts.is_file():
        raise CampaignError(f"pi-autoresearch index.ts not found at {index_ts} — image is broken")
    preserve = " ".join(
        f"-e {name}"
        for name in (
            "runs lanes hypotheses reviews baseline runtime state.json "
            "campaign.json adapter.json out-of-scope-suggestions.md"
        ).split()
    )
    pre_marker = "git clean -fd 2>/dev/null"
    post_marker = f"git clean -fd {preserve} 2>/dev/null"

    contents = index_ts.read_text()
    pre_count = contents.count(pre_marker)
    if pre_count > 0:
        if pre_count != 1:
            raise CampaignError(
                f"pi-autoresearch {index_ts.name}: expected exactly 1 `{pre_marker}` "
                f"occurrence, got {pre_count} — patch needs updating"
            )
        atomic_write(index_ts, contents.replace(pre_marker, post_marker))
        log(f"patched {index_ts.name} to preserve workspace dirs")
    elif post_marker in contents:
        pass
    else:
        raise CampaignError(
            f"pi-autoresearch {index_ts.name}: neither the pre- nor post-patch marker is "
            f"present — upstream shape changed, workspace-preservation patch needs updating"
        )


def _patch_pi_ai_anthropic_baseurl() -> None:
    gateway_base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    if not gateway_base:
        return

    candidates = [
        Path(
            "/usr/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@mariozechner/pi-ai/dist/models.generated.js"
        ),
        Path(
            "/usr/local/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@mariozechner/pi-ai/dist/models.generated.js"
        ),
    ]
    models_file = next((p for p in candidates if p.is_file()), None)
    if models_file is None:
        raise CampaignError("pi-ai models.generated.js not found in any known location — image is broken")

    contents = models_file.read_text()
    marker = '"https://api.anthropic.com"'
    occurrences = contents.count(marker)
    if occurrences == 0:
        if gateway_base in contents:
            log(f"pi-ai models.generated.js already points at {gateway_base}")
            return
        raise CampaignError(
            "pi-ai models.generated.js: neither the Anthropic baseUrl marker nor our gateway URL "
            "is present — pi-ai's bundle shape changed, baseUrl patch needs updating"
        )

    replacement = json.dumps(gateway_base)
    patched = contents.replace(marker, replacement)
    atomic_write(models_file, patched)
    log(f"patched pi-ai models.generated.js: rewrote {occurrences} Anthropic baseUrl occurrence(s) to {replacement}")
