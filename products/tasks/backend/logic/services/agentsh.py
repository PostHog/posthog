import shlex
from urllib.parse import urlparse

from django.conf import settings

import yaml

AGENTSH_DAEMON_PORT = 18080
SESSION_ID_FILE = "/tmp/agentsh-session-id"
ENV_FILE = "/tmp/agent-env"
ENV_WRAPPER_SCRIPT = "/tmp/agentsh-env-wrapper.sh"
# Sourced via BASH_ENV on every `bash -c` the agent runs, so git/gh pick up a
# mid-session GitHub credential refresh (the backend rewrites ENV_FILE in place).
BASH_ENV_SCRIPT = "/tmp/agentsh-bash-env.sh"
AGENTSH_AUDIT_DB = "/var/lib/agentsh/events.db"
INFRASTRUCTURE_DOMAINS = [
    "*.posthog.com",
    "api.anthropic.com",
    "gateway.us.posthog.com",
    "gateway.eu.posthog.com",
]


# Any failure parsing a `SANDBOX_*_URL` value (malformed scheme, non-string,
# bad port like `http://host:abc` / `:99999`) should degrade silently to "no
# host/port added" rather than crash `generate_policy_yaml` and block sandbox
# boot. A typo in `.env` shouldn't be a hard failure.
def _hostname_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except (ValueError, AttributeError):
        return None


def _port_from_url(url: str | None) -> int | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (ValueError, AttributeError):
        return None
    if port is not None:
        return port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


# Sandbox-host URLs in `.env` for local dev. Their hostnames and (non-standard)
# ports feed the DEBUG-only network rule below — e.g. llm-gateway on 3308, MCP
# wrangler on 8787 — so locally-hosted services pass the agentsh syscall-layer
# firewall. These settings are only read into the DEBUG rule; in prod they have
# no effect even if defined.
_DEBUG_SANDBOX_URL_SETTINGS = (
    "SANDBOX_API_URL",
    "SANDBOX_LLM_GATEWAY_URL",
    "SANDBOX_MCP_URL",
    "SANDBOX_AGENT_OTEL_LOGS_URL",
    "SANDBOX_AGENT_OTEL_TRACES_URL",
)


def _get_debug_only_domains() -> list[str]:
    """Hostnames added ONLY when DEBUG is on: dev loopback aliases plus any
    sandbox URL hosts parsed from `SANDBOX_*_URL` settings. Kept separate from
    the prod-safe `INFRASTRUCTURE_DOMAINS` set so a stray dev hostname can't
    accidentally widen prod's allowlist.
    """
    domains: list[str] = ["localhost", "host.docker.internal"]
    for setting_name in _DEBUG_SANDBOX_URL_SETTINGS:
        hostname = _hostname_from_url(getattr(settings, setting_name, None))
        if hostname and hostname not in domains:
            domains.append(hostname)
    return domains


def _get_debug_only_ports() -> list[int]:
    """Ports added ONLY when DEBUG is on. The prod-safe set is
    `[443, 80, 22]` (cloud routing only); in DEBUG we additionally expose
    Django (8000) and Caddy (8010), plus any non-standard ports parsed from
    `SANDBOX_*_URL` (e.g. llm-gateway 3308, MCP wrangler 8787). Without this,
    locally-hosted services on custom ports are denied at the agentsh
    syscall layer even when their hostname is allowed.
    """
    ports: list[int] = [8000, 8010]
    for setting_name in _DEBUG_SANDBOX_URL_SETTINGS:
        port = _port_from_url(getattr(settings, setting_name, None))
        if port is not None and port not in ports:
            ports.append(port)
    return ports


def generate_env_wrapper() -> str:
    """Generate a wrapper that restores the full sandbox environment.

    ``agentsh exec`` starts child processes with a heavily stripped
    environment.  We capture the sandbox env (via ``env -0``) *before*
    ``agentsh exec`` runs, then this wrapper re-exports every variable so
    the agent-server sees the same env it would without agentsh.

    Network policy enforcement happens at the syscall level (ptrace) —
    it does not depend on proxy environment variables.
    """
    return f"""\
#!/bin/bash
while IFS= read -r -d $'\\0' line; do
  export "$line"
done < {ENV_FILE}
exec "$@"
"""


def generate_bash_env_script() -> str:
    """
    Generate the script sourced via ``BASH_ENV``.
    """
    return f"""\
while IFS= read -r -d $'\\0' kv 2>/dev/null; do
  case "$kv" in
    GH_TOKEN=*|GITHUB_TOKEN=*) export "$kv" ;;
  esac
done < {ENV_FILE} 2>/dev/null
"""


def generate_config_yaml(*, enable_ptrace: bool = True, full_trace: bool = True) -> str:
    sandbox: dict = {
        "enabled": True,
        "allow_degraded": True,
        "fuse": {"enabled": False},
        "network": {"enabled": True},
        "cgroups": {"enabled": False},
        "unix_sockets": {"enabled": False},
    }

    if enable_ptrace:
        sandbox["ptrace"] = {
            "enabled": True,
            "attach_mode": "children",
            "trace": {
                "execve": full_trace,
                "file": full_trace,
                "network": True,
                "signal": full_trace,
            },
            "performance": {
                "seccomp_prefilter": False,
                "max_tracees": 500,
                "max_hold_ms": 5000,
            },
            "mask_tracer_pid": "off",
            "on_attach_failure": "fail_open",
        }

    config = {
        "server": {
            "http": {
                "addr": f"127.0.0.1:{AGENTSH_DAEMON_PORT}",
                "read_timeout": "0s",
                "write_timeout": "0s",
            },
            "grpc": {"enabled": False},
        },
        "auth": {"type": "none"},
        "logging": {
            "level": "info",
            "format": "text",
            "output": "stderr",
        },
        "sessions": {
            "base_dir": "/var/lib/agentsh/sessions",
            "max_sessions": 10,
            "default_timeout": "2h",
            "default_idle_timeout": "2h",
            "real_paths": True,
        },
        "audit": {
            "enabled": True,
            "storage": {"sqlite_path": AGENTSH_AUDIT_DB},
        },
        "sandbox": sandbox,
        "policies": {
            "dir": "/etc/agentsh/policies",
            "default_policy": "default",
        },
        "health": {
            "path": "/health",
            "readiness_path": "/ready",
        },
        "development": {
            "disable_auth": True,
            "verbose_errors": True,
        },
    }
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def generate_policy_yaml(allowed_domains: list[str] | None = None) -> str:
    """Generate agentsh policy YAML.

    When allowed_domains is set, only those domains (plus infrastructure) are
    reachable and everything else is denied.  When None, all network traffic
    is allowed (audit-only mode).
    """
    if allowed_domains is not None:
        prod_domains = list(allowed_domains)
        for domain in INFRASTRUCTURE_DOMAINS:
            if domain not in prod_domains:
                prod_domains.append(domain)

        network_rules: list[dict] = [
            {
                "name": "allow-localhost",
                "cidrs": ["127.0.0.0/8", "::1/128"],
                "decision": "allow",
            },
            {
                "name": "deny-cloud-metadata",
                "cidrs": ["169.254.169.254/32", "fd00:ec2::254/128"],
                "decision": "deny",
            },
            # Prod-safe allow rule: only the caller-provided domains plus our
            # baked-in infrastructure domains, and only the cloud-routing ports
            # (443, 80, 22). This rule is identical in every environment.
            {
                "name": "allow-domains",
                "domains": prod_domains,
                "ports": [443, 80, 22],
                "decision": "allow",
            },
        ]
        # DEBUG-only additions live in their own rule so a stray dev hostname
        # or port can't widen the prod allowlist by accident. Append after the
        # prod rule, before default-deny.
        if getattr(settings, "DEBUG", False):
            network_rules.append(
                {
                    "name": "allow-debug-domains",
                    "domains": _get_debug_only_domains(),
                    "ports": _get_debug_only_ports(),
                    "decision": "allow",
                }
            )
        network_rules.append(
            {
                "name": "default-deny-network",
                "domains": ["*"],
                "decision": "deny",
            }
        )
    else:
        network_rules = [
            {
                "name": "allow-all-network",
                "domains": ["*"],
                "decision": "allow",
            },
        ]

    policy: dict = {
        "version": 1,
        "name": "default",
        "description": "Agent sandbox policy",
        "network_rules": network_rules,
        "command_rules": [
            {
                "name": "allow-all-commands",
                "description": "Allow all commands (enforcement is network-only)",
                "commands": ["*"],
                "decision": "allow",
            },
        ],
        "file_rules": [
            {
                "name": "allow-all-files",
                "description": "Allow all file operations (enforcement is network-only)",
                "paths": ["**"],
                "operations": ["*"],
                "decision": "allow",
            },
        ],
        "env_policy": {
            "allow": [
                "HOME",
                "PATH",
                "USER",
                "SHELL",
                "TERM",
                "LANG",
                "LC_*",
                "TZ",
                "PWD",
                "OLDPWD",
                "HOSTNAME",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "NO_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "no_proxy",
                "all_proxy",
                "AGENTSH_*",
                "NODE_OPTIONS",
                "NODE_ENV",
                "NODE_PATH",
                "POSTHOG_*",
                "JWT_PUBLIC_KEY",
                "GITHUB_TOKEN",
                "LLM_GATEWAY_URL",
                "IS_SANDBOX",
                "PYTHONPATH",
            ],
            "deny": [],
            "block_iteration": False,
        },
    }
    return yaml.dump(policy, default_flow_style=False, sort_keys=False)


def build_audit_query_command(since_ns: int = 0, limit: int = 50) -> str:
    where_parts = []
    if since_ns > 0:
        where_parts.append(f"ts_unix_ns > {since_ns}")
    where_parts.append("(type LIKE 'net%' OR (effective_decision IS NOT NULL AND domain IS NOT NULL))")
    where_clause = " AND ".join(where_parts)
    query = (
        "SELECT ts_unix_ns, type, domain, remote, effective_decision, policy_rule "
        f"FROM events "
        f"WHERE {where_clause} "
        f"ORDER BY ts_unix_ns DESC LIMIT {limit};"
    )
    return f"sqlite3 -json {shlex.quote(AGENTSH_AUDIT_DB)} {shlex.quote(query)} 2>/dev/null || echo '[]'"


def build_exec_prefix() -> str:
    return f"agentsh exec --client-timeout 2h --timeout 2h $(cat {SESSION_ID_FILE}) --"


def build_setup_script(workspace_path: str) -> str:
    return (
        f"rm -f {SESSION_ID_FILE} {SESSION_ID_FILE}.tmp; "
        f"nohup agentsh server --config /etc/agentsh/config.yaml > /var/log/agentsh/agentsh.log 2>&1 & "
        f"AGENTSH_OK=0; "
        f"for i in $(seq 1 30); do "
        f"  status=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{AGENTSH_DAEMON_PORT}/health); "
        f'  [ "$status" = "200" ] && AGENTSH_OK=1 && break; '
        f"  sleep 0.5; "
        f"done; "
        f'if [ "$AGENTSH_OK" != "1" ]; then '
        f"  echo 'agentsh daemon failed to start' >&2; "
        f"  cat /var/log/agentsh/agentsh.log >&2 2>/dev/null; "
        f"  exit 1; "
        f"fi; "
        f"SESSION_ID=$(agentsh session create --workspace {workspace_path} --policy default --json | jq -r .id); "
        f'if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then '
        f"  echo 'agentsh session create failed' >&2; "
        f"  exit 1; "
        f"fi; "
        f'printf %s "$SESSION_ID" > {SESSION_ID_FILE}.tmp && mv {SESSION_ID_FILE}.tmp {SESSION_ID_FILE}'
    )
