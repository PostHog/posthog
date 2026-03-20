from django.conf import settings

import yaml

AGENTSH_DAEMON_PORT = 18080
SESSION_ID_FILE = "/tmp/agentsh-session-id"
ENV_FILE = "/tmp/agent-env"
ENV_WRAPPER_SCRIPT = "/tmp/agentsh-env-wrapper.sh"
INFRASTRUCTURE_DOMAINS = [
    "*.posthog.com",
    "api.anthropic.com",
]


def generate_env_wrapper() -> str:
    """Generate the env wrapper script for agentsh exec.

    agentsh exec creates a clean environment, stripping container env vars.
    This wrapper restores them from a null-delimited dump created before exec,
    then configures Node.js to use the agentsh HTTP proxy
    """
    no_proxy_domains = ",".join(INFRASTRUCTURE_DOMAINS)
    if getattr(settings, "DEBUG", False):
        no_proxy_domains += ",localhost,host.docker.internal"

    return f"""\
#!/bin/bash
while IFS= read -r -d $'\\0' line; do
  export "$line"
done < {ENV_FILE}
# Prevent the agent-server from calling agentsh exec for tool execution.
# The outer agentsh exec already enforces network rules on all children.
unset AGENTSH_IN_SESSION AGENTSH_SESSION_ID
# agentsh exec routes traffic through an HTTP proxy (HTTP_PROXY/HTTPS_PROXY).
# Node.js fetch() ignores proxy env vars by default; --use-env-proxy fixes this.
export NODE_OPTIONS="${{NODE_OPTIONS:+$NODE_OPTIONS }}--use-env-proxy"
# Infrastructure domains bypass the proxy — the agentsh proxy may not handle
# streaming connections well, and these domains are always allowed in the policy.
export NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{no_proxy_domains}"
export no_proxy="${{no_proxy:+$no_proxy,}}{no_proxy_domains}"
exec "$@"
"""


def generate_config_yaml(*, enable_ptrace: bool = False, full_trace: bool = False) -> str:
    """Generate agentsh config YAML.

    Args:
        enable_ptrace: Explicitly enable ptrace-based enforcement
        full_trace: When True, trace all syscall types (execve, file, network, signal).
                    When False (default), only trace network — avoids process-killing
                    issues observed in Docker containers with full tracing.
    """
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
                # gVisor doesn't support seccomp BPF injection
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
            "storage": {"sqlite_path": "/var/lib/agentsh/events.db"},
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


def _get_infrastructure_domains() -> list[str]:
    """Domains that must always be reachable for the agent to function."""
    domains = list(INFRASTRUCTURE_DOMAINS)
    if getattr(settings, "DEBUG", False):
        domains.extend(["localhost", "host.docker.internal"])
    return domains


def generate_policy_yaml(allowed_domains: list[str]) -> str:
    """Generate agentsh policy YAML.

    allowed_domains should be the pre-computed effective domain list
    from SandboxEnvironment.get_effective_domains(). Infrastructure
    domains (PostHog API, LLM gateway) are always injected.
    """
    merged = list(allowed_domains)
    for d in _get_infrastructure_domains():
        if d not in merged:
            merged.append(d)

    # In dev for PostHog API
    allowed_ports = [443, 80, 22]
    if getattr(settings, "DEBUG", False):
        allowed_ports.extend([8000, 8010])

    policy: dict = {
        "version": 1,
        "name": "default",
        "description": "Agent sandbox policy with domain allowlisting",
        "network_rules": [
            {
                "name": "allow-localhost",
                "description": "Allow localhost connections (includes Docker DNS at 127.0.0.11)",
                "cidrs": ["127.0.0.0/8", "::1/128"],
                "decision": "allow",
            },
            {
                "name": "allow-domains",
                "description": "Allowed domains for this sandbox",
                "domains": merged,
                "ports": allowed_ports,
                "decision": "allow",
            },
            {
                "name": "default-deny-network",
                "description": "Deny all other network connections",
                "domains": ["*"],
                "decision": "deny",
            },
        ],
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
                # System
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
                # Proxy (set by agentsh exec)
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "NO_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "no_proxy",
                "all_proxy",
                # agentsh
                "AGENTSH_*",
                # Node.js
                "NODE_OPTIONS",
                "NODE_ENV",
                "NODE_PATH",
                # PostHog agent-server
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


AGENTSH_AUDIT_DB = "/var/lib/agentsh/events.db"


def build_audit_query_command(since_ns: int = 0, limit: int = 50) -> str:
    """Shell command to query agentsh audit DB for network policy events."""
    where_parts = []
    if since_ns > 0:
        where_parts.append(f"ts_unix_ns > {since_ns}")
    where_parts.append("(type LIKE 'net%' OR (effective_decision IS NOT NULL AND domain IS NOT NULL))")
    where_clause = " AND ".join(where_parts)
    return (
        f"sqlite3 -json {AGENTSH_AUDIT_DB} "
        f'"SELECT ts_unix_ns, type, domain, remote, effective_decision, policy_rule '
        f"FROM events "
        f"WHERE {where_clause} "
        f"ORDER BY ts_unix_ns DESC LIMIT {limit};\" 2>/dev/null || echo '[]'"
    )


def build_exec_prefix() -> str:
    return f"agentsh exec --client-timeout 2h --timeout 2h $(cat {SESSION_ID_FILE}) --"


def build_setup_script(workspace_path: str) -> str:
    return (
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
        f"agentsh session create --workspace {workspace_path} --policy default --json "
        f"| jq -r .id > {SESSION_ID_FILE}"
    )
