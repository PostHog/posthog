import shlex
from urllib.parse import urlparse

from django.conf import settings

import yaml

AGENTSH_DAEMON_PORT = 18080
SESSION_ID_FILE = "/tmp/agentsh-session-id"
ENV_FILE = "/tmp/agent-env"
ENV_WRAPPER_SCRIPT = "/tmp/agentsh-env-wrapper.sh"
AGENTSH_AUDIT_DB = "/var/lib/agentsh/events.db"
INFRASTRUCTURE_DOMAINS = [
    "*.posthog.com",
    "api.anthropic.com",
    "gateway.us.posthog.com",
    "gateway.eu.posthog.com",
]


def _hostname_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.hostname


def _get_infrastructure_domains() -> list[str]:
    domains = list(INFRASTRUCTURE_DOMAINS)

    for candidate in [
        getattr(settings, "SANDBOX_API_URL", None),
        getattr(settings, "SANDBOX_LLM_GATEWAY_URL", None),
    ]:
        hostname = _hostname_from_url(candidate)
        if hostname and hostname not in domains:
            domains.append(hostname)

    if getattr(settings, "DEBUG", False):
        for hostname in ["localhost", "host.docker.internal"]:
            if hostname not in domains:
                domains.append(hostname)

    return domains


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
        merged_domains = list(allowed_domains)
        for domain in _get_infrastructure_domains():
            if domain not in merged_domains:
                merged_domains.append(domain)

        allowed_ports = [443, 80, 22]
        if getattr(settings, "DEBUG", False):
            allowed_ports.extend([8000, 8010])

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
            {
                "name": "allow-domains",
                "domains": merged_domains,
                "ports": allowed_ports,
                "decision": "allow",
            },
            {
                "name": "default-deny-network",
                "domains": ["*"],
                "decision": "deny",
            },
        ]
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
