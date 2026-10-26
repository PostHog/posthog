import shlex
import base64

from posthog.dataclasses import frozen

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
from .task_filesystem import TASK_FILESYSTEM_SCRIPT, read_task_filesystem_script, task_filesystem_command


@frozen
class LaunchFile:
    path: str
    payload: bytes
    mode: str


def build_modal_launch_preparation_script(allowed_domains: list[str] | None) -> str:
    files = _base_files()
    if allowed_domains is not None:
        files.extend(_agentsh_files(allowed_domains))
    script = _script_header()
    script.extend(_install_lines(files))
    script.extend(_installed_lines())
    if allowed_domains is not None:
        script.extend(_daemon_session_lines())
    return "\n".join(script) + "\n"


def build_modal_agent_server_launch_script(
    allowed_domains: list[str] | None, *, bundled_skills_clear_command: str, preflight_lines: list[str]
) -> str:
    script = _script_header()
    script.extend(_install_lines(_base_files()))
    script.extend(_installed_lines())
    script.extend(
        [
            "stage=bundled_skills",
            f"(umask 022 && {task_filesystem_command(bundled_skills_clear_command)})",
            "stage=preflight",
            "set +euo pipefail",
            *preflight_lines,
            "set -euo pipefail",
        ]
    )
    if allowed_domains is not None:
        script.append("stage=install")
        script.extend(_install_lines(_agentsh_files(allowed_domains)))
        script.append("installed_at=$(date +%s%3N)")
        script.extend(_daemon_session_lines())
    return "\n".join(script) + "\n"


def _base_files() -> list[LaunchFile]:
    return [
        LaunchFile(path=BASH_ENV_SCRIPT, payload=generate_bash_env_script().encode(), mode="644"),
        LaunchFile(path=GH_GUARD_INSTALL_PATH, payload=read_gh_guard_script(), mode="755"),
        LaunchFile(path=TASK_FILESYSTEM_SCRIPT, payload=read_task_filesystem_script(), mode="644"),
    ]


def _agentsh_files(allowed_domains: list[str]) -> list[LaunchFile]:
    return [
        LaunchFile(
            path="/etc/agentsh/config.yaml",
            payload=generate_config_yaml(enable_ptrace=True, full_trace=True).encode(),
            mode="644",
        ),
        LaunchFile(
            path="/etc/agentsh/policies/default.yaml",
            payload=generate_policy_yaml(allowed_domains).encode(),
            mode="644",
        ),
        LaunchFile(path=ENV_WRAPPER_SCRIPT, payload=generate_env_wrapper().encode(), mode="755"),
    ]


def _script_header() -> list[str]:
    return [
        "#!/bin/bash",
        "set -euo pipefail",
        "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
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


def _install_lines(files: list[LaunchFile]) -> list[str]:
    lines: list[str] = ["first_staged=${#staged_files[@]}"]
    for file in files:
        destination = shlex.quote(file.path)
        encoded = shlex.quote(base64.b64encode(file.payload).decode())
        lines.extend(
            [
                f'mkdir -p -- "$(dirname -- {destination})"',
                f"temporary=$(mktemp {shlex.quote(file.path + '.tmp.XXXXXX')})",
                'staged_files+=("$temporary")',
                f'printf %s {encoded} | base64 -d > "$temporary"',
                f'chmod {file.mode} "$temporary"',
            ]
        )
    for index, file in enumerate(files):
        lines.append(f"test ! -d {shlex.quote(file.path)}")
        lines.append(f'mv -f -- "${{staged_files[$((first_staged + {index}))]}}" {shlex.quote(file.path)}')
    return lines


def _installed_lines() -> list[str]:
    return [
        "installed_at=$(date +%s%3N)",
        'printf "__posthog_launch_preparation_install_ms=%s\\n" "$((installed_at - started_at))"',
    ]


def _daemon_session_lines() -> list[str]:
    return [
        "stage=daemon_session",
        "pkill -f '[a]gentsh server' || [ $? -eq 1 ]",
        "for i in $(seq 1 50); do",
        "    if ! pgrep -f '[a]gentsh server' > /dev/null; then break; fi",
        "    sleep 0.1",
        "done",
        "if pgrep -f '[a]gentsh server' > /dev/null; then exit 1; fi",
        "mkdir -p /var/log/agentsh /var/lib/agentsh/sessions",
        f"rm -f -- {shlex.quote(SESSION_ID_FILE)}",
        f"nohup /usr/bin/python3 -I {TASK_FILESYSTEM_SCRIPT} enter -- /usr/bin/agentsh server --config /etc/agentsh/config.yaml > /var/log/agentsh/agentsh.log 2>&1 &",
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
        f"session_id=$(timeout 60s /usr/bin/agentsh session create --workspace {shlex.quote(DEFAULT_SANDBOX_WORKING_DIR)} --policy default --json | jq -er '.id | select(type == \"string\" and length > 0)')",
        f"temporary=$(mktemp {shlex.quote(SESSION_ID_FILE + '.tmp.XXXXXX')})",
        'staged_files+=("$temporary")',
        'printf %s "$session_id" > "$temporary"',
        f'mv -f -- "$temporary" {shlex.quote(SESSION_ID_FILE)}',
        f"test -s {shlex.quote(SESSION_ID_FILE)}",
        'printf "__posthog_launch_preparation_daemon_session_ms=%s\\n" "$(($(date +%s%3N) - installed_at))"',
    ]
