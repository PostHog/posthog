import shlex
import base64

from products.tasks.backend.constants import DEFAULT_SANDBOX_WORKING_DIR

from .agentsh import (
    AGENTSH_DAEMON_PORT,
    BASH_ENV_SCRIPT,
    ENV_WRAPPER_SCRIPT,
    GH_GUARD_INSTALL_PATH,
    SESSION_ID_FILE,
    generate_bash_env_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
    read_gh_guard_script,
)


def build_modal_launch_preparation_script(allowed_domains: list[str] | None) -> str:
    files = [
        (BASH_ENV_SCRIPT, generate_bash_env_script().encode(), "644"),
        (GH_GUARD_INSTALL_PATH, read_gh_guard_script(), "755"),
    ]
    if allowed_domains is not None:
        files.extend(
            [
                ("/etc/agentsh/config.yaml", generate_config_yaml(enable_ptrace=True, full_trace=True).encode(), "644"),
                ("/etc/agentsh/policies/default.yaml", generate_policy_yaml(allowed_domains).encode(), "644"),
                (ENV_WRAPPER_SCRIPT, generate_env_wrapper().encode(), "755"),
            ]
        )

    script = [
        "#!/bin/bash",
        "set -euo pipefail",
        "umask 077",
        "stage=install",
        "staged_files=()",
        'daemon_pid=""',
        "started_at=$(date +%s%3N)",
        "cleanup() {",
        "    result=$?",
        "    trap - EXIT",
        '    if [ "$result" -ne 0 ] && [ -n "$daemon_pid" ]; then',
        '        kill "$daemon_pid" 2>/dev/null || true',
        "        for i in $(seq 1 20); do",
        '            if ! kill -0 "$daemon_pid" 2>/dev/null; then break; fi',
        "            sleep 0.1",
        "        done",
        '        kill -KILL "$daemon_pid" 2>/dev/null || true',
        '        wait "$daemon_pid" 2>/dev/null || true',
        "    fi",
        '    if [ "$result" -ne 0 ]; then printf "__posthog_launch_preparation_failed=%s\\n" "$stage" >&2; fi',
        '    rm -f -- "${staged_files[@]}" "$0" || true',
        '    exit "$result"',
        "}",
        "trap cleanup EXIT",
    ]
    for path, payload, mode in files:
        destination = shlex.quote(path)
        encoded = shlex.quote(base64.b64encode(payload).decode())
        script.extend(
            [
                f'mkdir -p -- "$(dirname -- {destination})"',
                f"temporary=$(mktemp {shlex.quote(path + '.tmp.XXXXXX')})",
                'staged_files+=("$temporary")',
                f'printf %s {encoded} | base64 -d > "$temporary"',
                f'chmod {mode} "$temporary"',
            ]
        )
    for index, (path, _, _) in enumerate(files):
        script.append(f"test ! -d {shlex.quote(path)}")
        script.append(f'mv -f -- "${{staged_files[{index}]}}" {shlex.quote(path)}')
    script.extend(
        [
            "installed_at=$(date +%s%3N)",
            'printf "__posthog_launch_preparation_install_ms=%s\\n" "$((installed_at - started_at))"',
        ]
    )

    if allowed_domains is not None:
        script.extend(
            [
                "stage=daemon_session",
                "pkill -f '[a]gentsh server' || [ $? -eq 1 ]",
                "for i in $(seq 1 50); do",
                "    if ! pgrep -f '[a]gentsh server' > /dev/null; then break; fi",
                "    sleep 0.1",
                "done",
                "if pgrep -f '[a]gentsh server' > /dev/null; then exit 1; fi",
                "mkdir -p /var/log/agentsh /var/lib/agentsh/sessions",
                f"rm -f -- {shlex.quote(SESSION_ID_FILE)}",
                "nohup agentsh server --config /etc/agentsh/config.yaml > /var/log/agentsh/agentsh.log 2>&1 &",
                "daemon_pid=$!",
                "healthy=0",
                "for i in $(seq 1 30); do",
                f"    if [ \"$(curl -s --max-time 1 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{AGENTSH_DAEMON_PORT}/health || true)\" = 200 ]; then",
                "        healthy=1",
                "        break",
                "    fi",
                "    sleep 0.5",
                "done",
                '[ "$healthy" -eq 1 ]',
                'kill -0 "$daemon_pid"',
                f"session_id=$(agentsh session create --workspace {shlex.quote(DEFAULT_SANDBOX_WORKING_DIR)} --policy default --json | jq -er '.id | select(type == \"string\" and length > 0)')",
                f"temporary=$(mktemp {shlex.quote(SESSION_ID_FILE + '.tmp.XXXXXX')})",
                'staged_files+=("$temporary")',
                'printf %s "$session_id" > "$temporary"',
                f'mv -f -- "$temporary" {shlex.quote(SESSION_ID_FILE)}',
                f"test -s {shlex.quote(SESSION_ID_FILE)}",
                'printf "__posthog_launch_preparation_daemon_session_ms=%s\\n" "$(($(date +%s%3N) - installed_at))"',
            ]
        )
    return "\n".join(script) + "\n"
