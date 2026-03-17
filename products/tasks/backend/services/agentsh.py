import yaml

AGENTSH_DAEMON_PORT = 18080
SESSION_ID_FILE = "/tmp/agentsh-session-id"


def generate_config_yaml() -> str:
    config = {
        "server": {
            "http": {
                "addr": f"127.0.0.1:{AGENTSH_DAEMON_PORT}",
                "read_timeout": "30s",
                "write_timeout": "60s",
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
            "default_timeout": "1h",
            "default_idle_timeout": "15m",
            "real_paths": True,
        },
        "audit": {
            "enabled": True,
            "storage": {"sqlite_path": "/var/lib/agentsh/events.db"},
        },
        "sandbox": {
            "enabled": True,
            "allow_degraded": True,
            "ptrace": {
                "enabled": True,
                "attach_mode": "children",
                "mask_tracer_pid": "off",
                "trace": {
                    "execve": True,
                    "file": True,
                    "network": True,
                    "signal": True,
                },
                "performance": {
                    "seccomp_prefilter": False,
                    "max_tracees": 500,
                    "max_hold_ms": 5000,
                },
                "on_attach_failure": "fail_open",
            },
            "fuse": {"enabled": False},
            "network": {
                "enabled": True,
                "intercept_mode": "all",
            },
            "cgroups": {"enabled": False},
            "unix_sockets": {"enabled": False},
        },
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


def generate_policy_yaml(allowed_domains: list[str]) -> str:
    """Generate agentsh policy YAML.

    allowed_domains should be the pre-computed effective domain list
    from SandboxEnvironment.get_effective_domains().
    """
    policy: dict = {
        "version": 1,
        "name": "default",
        "description": "Agent sandbox policy with domain allowlisting",
        "network_rules": [
            {
                "name": "allow-localhost",
                "description": "Allow localhost connections",
                "cidrs": ["127.0.0.1/32", "::1/128"],
                "decision": "allow",
            },
            {
                "name": "allow-domains",
                "description": "Allowed domains for this sandbox",
                "domains": list(allowed_domains),
                "ports": [443, 80, 22],
                "decision": "allow",
            },
            {
                "name": "default-deny-network",
                "description": "Deny all other network connections",
                "domains": ["*"],
                "decision": "deny",
            },
        ],
    }
    return yaml.dump(policy, default_flow_style=False, sort_keys=False)


def build_exec_prefix() -> str:
    return f"agentsh exec $(cat {SESSION_ID_FILE}) --"


def build_setup_script(workspace_path: str) -> str:
    return (
        f"nohup agentsh server --config /etc/agentsh/config.yaml > /var/log/agentsh/agentsh.log 2>&1 & "
        f"for i in $(seq 1 30); do "
        f"  status=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{AGENTSH_DAEMON_PORT}/health); "
        f'  [ "$status" = "200" ] && break; '
        f"  sleep 0.5; "
        f"done; "
        f"agentsh session create --workspace {workspace_path} --policy default --json "
        f"| jq -r .id > {SESSION_ID_FILE}"
    )
