from __future__ import annotations

import io
import os
import sys
import enum
import json
import time
import shlex
import shutil
import socket
import contextlib
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import click
from hogli.manifest import REPO_ROOT, get_manifest

from products.tasks.backend.logic.services.mcp_url import LOCAL_HOSTNAMES, resolve_mcp_url

from . import doctor

FLOX_DOTENV_FILE = ".env"
TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})

SANDBOX_BACKEND_DOCKER = "docker"
SANDBOX_BACKEND_MODAL = "modal"
SANDBOX_BACKEND_HOGLAND = "hogland"
MODAL_BACKENDS = frozenset({SANDBOX_BACKEND_MODAL, "modal_docker", "modal_evals"})
MODAL_TOKEN_KEYS = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
MODAL_CONFIG_PATH = Path.home() / ".modal.toml"
NON_PUBLIC_HOSTNAMES = frozenset({*LOCAL_HOSTNAMES, "host.docker.internal"})
OPTIONAL_TARGETS = frozenset({"mcp"})
TAILSCALE_APP_BINARY = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
FUNNEL_HOST_SUFFIX = ".ts.net"
FUNNEL_PUBLIC_PORTS = (443, 8443, 10000)
NGROK_HOST_SUFFIXES = (".ngrok.app", ".ngrok.io", ".ngrok.dev", ".ngrok-free.app", ".ngrok-free.dev")
DJANGO_PORT_DEFAULT = 8000
SANDBOX_BASE_IMAGE = "posthog-sandbox-base"

LLM_GATEWAY_PORT_DEFAULT = 3308
MCP_SERVER_URL_DEFAULT = "http://localhost:8787/mcp"
TEMPORAL_HOST = "localhost"
TEMPORAL_PORT = 7233
TEMPORAL_TASK_QUEUE = "development-task-queue"

WORKER_UNIT = "temporal-worker"
LLM_GATEWAY_UNIT = "llm-gateway"
UNIT_COMMAND_MARKERS: dict[str, tuple[str, ...]] = {
    WORKER_UNIT: ("start_temporal_worker", TEMPORAL_TASK_QUEUE),
    LLM_GATEWAY_UNIT: ("llm_gateway.main:app",),
}
PROCESS_START_FORMAT = "%a %b %d %H:%M:%S %Y"

HTTP_TIMEOUT_SECONDS = 2.0
PUBLIC_HTTP_TIMEOUT_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 10.0
SANDBOX_PROBE_TIMEOUT_SECONDS = 30.0
DATABASE_CHECK_TIMEOUT_SECONDS = 120.0
SANDBOX_CURL_MAX_TIME_SECONDS = 3

SETUP_FIX = "python manage.py setup_background_agents"
GITHUB_APP_FIX = "python manage.py create_github_app"
INTENT_FIX = "hogli dev:setup  (enable the tasks intent)"
FLOX_FIX = "direnv reload  (or: flox activate)"
MODAL_TOKEN_FIX = "add MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to .env.local (1Password: Modal Development Token)"
FUNNEL_POLICY_DOC = "posthog-cloud-infra docs/TAILSCALE_FUNNEL.md"
TUNNEL_FIX = "expose them publicly, see docs/internal/sandboxes-setup-guide.md (Tunnel gateway, API, and MCP)"


class Status(enum.Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Check:
    id: str
    status: Status
    summary: str
    fix: str | None = None

    def to_json(self) -> dict[str, str]:
        result = {"id": self.id, "status": self.status.value, "summary": self.summary}
        if self.fix is not None:
            result["fix"] = self.fix
        return result


@dataclass(frozen=True)
class EnvLayers:
    files: tuple[tuple[str, Mapping[str, str]], ...]
    environ: Mapping[str, str]
    secret_marker: str


@dataclass(frozen=True)
class EnvResolution:
    value: str | None
    source: str | None
    conflicting_sources: tuple[str, ...]
    secret_reference_source: str | None


@dataclass(frozen=True)
class EnvRequirement:
    key: str
    missing_status: Status
    fix: str | None
    validate: Callable[[str], str | None] | None = None
    optional: bool = False


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, _, value = line.partition("=")
        values[name.strip()] = unquote(value.strip())
    return values


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def env_layer_paths(repo_root: Path) -> list[Path]:
    manifest = get_manifest()
    secrets = manifest.secrets_config
    paths = [repo_root / FLOX_DOTENV_FILE]
    if secrets is not None:
        paths.append(Path(secrets["file"]))
    paths.extend(manifest.env_files)
    return paths


def secret_marker() -> str:
    secrets = get_manifest().secrets_config
    return secrets["marker"] if secrets is not None else ""


def load_env_layers(paths: Sequence[Path], environ: Mapping[str, str], marker: str) -> EnvLayers:
    files: list[tuple[str, Mapping[str, str]]] = []
    for path in paths:
        try:
            files.append((path.name, parse_env_text(path.read_text())))
        except (FileNotFoundError, IsADirectoryError):
            continue
    return EnvLayers(
        files=tuple(files),
        environ={key: unquote(value) for key, value in environ.items()},
        secret_marker=marker,
    )


def is_secret_reference(value: str, layers: EnvLayers) -> bool:
    return bool(layers.secret_marker) and layers.secret_marker in value


def resolve_env_key(key: str, layers: EnvLayers) -> EnvResolution:
    defined = [(name, values[key]) for name, values in layers.files if values.get(key)]
    plain = [(name, file_value) for name, file_value in defined if not is_secret_reference(file_value, layers)]
    secret_reference_source = next(
        (name for name, file_value in defined if is_secret_reference(file_value, layers)),
        None,
    )
    environ_value = layers.environ.get(key) or None

    value: str | None = None
    source: str | None = None
    if environ_value is not None and all(file_value != environ_value for _, file_value in plain):
        value, source = environ_value, "shell"
    elif plain:
        source, value = plain[0]

    conflicting: tuple[str, ...] = ()
    if len({file_value for _, file_value in plain}) > 1:
        conflicting = tuple(name for name, _ in plain)
    return EnvResolution(
        value=value,
        source=source,
        conflicting_sources=conflicting,
        secret_reference_source=secret_reference_source,
    )


def dotenv_drift(layers: EnvLayers) -> list[str]:
    dotenv = next((values for name, values in layers.files if name == FLOX_DOTENV_FILE), {})
    return sorted(
        key
        for key, file_value in dotenv.items()
        if file_value and not is_secret_reference(file_value, layers) and layers.environ.get(key) != file_value
    )


def check_dotenv_loaded(layers: EnvLayers) -> Check:
    drifted = dotenv_drift(layers)
    if not drifted:
        return Check("env.dotenv", Status.OK, ".env is loaded in this shell")
    return Check(
        "env.dotenv",
        Status.WARN,
        f"{len(drifted)} key(s) from .env are missing or different in this shell; flox applies .env on "
        "activation, so a stack started from this shell would miss them",
        FLOX_FIX,
    )


def validate_pem(value: str) -> str | None:
    if "-----BEGIN" not in value or "PRIVATE KEY-----" not in value:
        return "not a PEM private key"
    return None


def validate_github_client_id(value: str) -> str | None:
    if value.isdigit():
        return "looks like the numeric App ID, use the Client ID (starts with Iv)"
    return None


def validate_http_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "not an http(s) URL"
    return None


def validate_sandbox_mcp_url(value: str) -> str | None:
    problem = validate_http_url(value)
    if problem is not None:
        return problem
    if urlparse(value).hostname in LOCAL_HOSTNAMES:
        return "localhost inside the sandbox is the container itself, use host.docker.internal"
    return None


def validate_truthy(value: str) -> str | None:
    if value.strip().lower() not in TRUTHY_VALUES:
        return "must be truthy for local sandbox providers"
    return None


ENV_REQUIREMENTS: tuple[EnvRequirement, ...] = (
    EnvRequirement("DEBUG", Status.ERROR, FLOX_FIX, validate_truthy),
    EnvRequirement("SANDBOX_JWT_PRIVATE_KEY", Status.ERROR, SETUP_FIX, validate_pem),
    EnvRequirement("OIDC_RSA_PRIVATE_KEY", Status.ERROR, SETUP_FIX, validate_pem),
    EnvRequirement(
        "SANDBOX_LLM_GATEWAY_URL",
        Status.ERROR,
        f"add SANDBOX_LLM_GATEWAY_URL=http://host.docker.internal:{LLM_GATEWAY_PORT_DEFAULT} to .env.local",
        validate_http_url,
    ),
    EnvRequirement("SANDBOX_MCP_URL", Status.OK, SETUP_FIX, validate_sandbox_mcp_url, optional=True),
    EnvRequirement(
        "LLM_GATEWAY_ANTHROPIC_API_KEY",
        Status.ERROR,
        "add LLM_GATEWAY_ANTHROPIC_API_KEY to .env.local (ask a human for the key)",
    ),
    EnvRequirement("GITHUB_APP_CLIENT_ID", Status.ERROR, GITHUB_APP_FIX, validate_github_client_id),
    EnvRequirement("GITHUB_APP_CLIENT_SECRET", Status.ERROR, GITHUB_APP_FIX),
    EnvRequirement("GITHUB_APP_SLUG", Status.ERROR, GITHUB_APP_FIX),
    EnvRequirement("GITHUB_APP_PRIVATE_KEY", Status.ERROR, GITHUB_APP_FIX, validate_pem),
    EnvRequirement("WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID", Status.WARN, "restore it in .env.development"),
)

SERVICE_ENV_KEYS = (
    "LLM_GATEWAY_PORT",
    "MCP_SERVER_URL",
    "SANDBOX_API_URL",
    "SANDBOX_LLM_GATEWAY_URL",
    "SANDBOX_MCP_URL",
    "SITE_URL",
    *MODAL_TOKEN_KEYS,
)


def check_env_requirement(requirement: EnvRequirement, layers: EnvLayers) -> Check:
    check_id = f"env.{requirement.key}"
    resolution = resolve_env_key(requirement.key, layers)

    if resolution.value is None:
        if resolution.secret_reference_source is not None:
            return Check(check_id, Status.OK, f"secret reference in {resolution.secret_reference_source}")
        if requirement.optional:
            return Check(check_id, Status.OK, "unset, default applies")
        return Check(check_id, requirement.missing_status, "unset", requirement.fix)

    if requirement.validate is not None:
        problem = requirement.validate(resolution.value)
        if problem is not None:
            return Check(check_id, Status.ERROR, f"{problem} (from {resolution.source})", requirement.fix)

    conflict = conflict_check(check_id, resolution)
    if conflict is not None:
        return conflict
    return Check(check_id, Status.OK, f"set (from {resolution.source})")


def conflict_check(check_id: str, resolution: EnvResolution) -> Check | None:
    if not resolution.conflicting_sources or resolution.source == "shell":
        return None
    sources = ", ".join(resolution.conflicting_sources)
    summary = f"different values in {sources}; {resolution.source} wins"
    return Check(check_id, Status.WARN, summary, "keep one definition")


def effective_environ(layers: EnvLayers) -> dict[str, str]:
    environ: dict[str, str] = {}
    for key in SERVICE_ENV_KEYS:
        value = resolve_env_key(key, layers).value
        if value is not None:
            environ[key] = value
    return environ


def sandbox_backend(provider: str | None) -> str:
    if provider == SANDBOX_BACKEND_DOCKER:
        return SANDBOX_BACKEND_DOCKER
    if provider and provider.upper() in ("MODAL_DOCKER", "MODAL_EVALS"):
        return provider.lower()
    if provider and provider.lower() == SANDBOX_BACKEND_HOGLAND:
        return SANDBOX_BACKEND_HOGLAND
    return SANDBOX_BACKEND_MODAL


def check_sandbox_provider(resolution: EnvResolution, backend: str) -> Check:
    check_id = "env.SANDBOX_PROVIDER"
    if resolution.value is None:
        return Check(
            check_id,
            Status.WARN,
            "unset, runs go to the production Modal app",
            "set SANDBOX_PROVIDER=docker (or MODAL_DOCKER) in .env.local",
        )
    conflict = conflict_check(check_id, resolution)
    if conflict is not None:
        return conflict
    if backend == SANDBOX_BACKEND_HOGLAND:
        return Check(check_id, Status.WARN, "hogland: no hogland checks exist yet, sandbox checks skipped")
    if backend != SANDBOX_BACKEND_MODAL or resolution.value == SANDBOX_BACKEND_MODAL:
        return Check(check_id, Status.OK, f"{backend} (from {resolution.source})")
    return Check(
        check_id,
        Status.WARN,
        f"{resolution.value} is not a known provider, runs go to the production Modal app",
        "use docker (lowercase), MODAL_DOCKER, or modal",
    )


def run_command(
    command: Sequence[str], timeout_seconds: float, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=dict(env) if env is not None else None,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None


def http_ok(url: str, timeout_seconds: float = HTTP_TIMEOUT_SECONDS) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=HTTP_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def check_docker() -> Check:
    result = doctor._check_docker()
    status = Status.OK if result.status == doctor.CheckStatus.OK else Status.ERROR
    return Check("svc.docker", status, result.summary, result.remediation)


def local_mcp_port(environ: Mapping[str, str]) -> int:
    port = urlparse(environ.get("MCP_SERVER_URL") or MCP_SERVER_URL_DEFAULT).port
    return port or urlparse(MCP_SERVER_URL_DEFAULT).port or 8787


def check_llm_gateway(environ: Mapping[str, str]) -> Check:
    base_url = f"http://localhost:{environ.get('LLM_GATEWAY_PORT') or LLM_GATEWAY_PORT_DEFAULT}"
    if http_ok(f"{base_url}/_liveness"):
        return Check("svc.llm_gateway", Status.OK, f"healthy on {base_url}")
    return Check(
        "svc.llm_gateway",
        Status.ERROR,
        f"not answering on {base_url}",
        "start the llm-gateway process (hogli start), or enable the tasks intent",
    )


def check_mcp_server(environ: Mapping[str, str]) -> Check:
    base_url = f"http://localhost:{local_mcp_port(environ)}"
    if http_ok(f"{base_url}/health"):
        return Check("svc.mcp", Status.OK, f"healthy on {base_url}")
    return Check(
        "svc.mcp",
        Status.WARN,
        f"not answering on {base_url}, agents run without PostHog MCP tools",
        "check the mcp process log (.posthog/.generated/logs/mcp.log); if absent, enable the mcp intent",
    )


def scan_unit_processes(repo_root: Path) -> dict[str, list[doctor.DevProcess]]:
    with contextlib.redirect_stdout(io.StringIO()):
        processes = doctor._scan_posthog_processes(repo_root)
    return {
        unit: [process for process in processes if all(marker in process.cmdline for marker in markers)]
        for unit, markers in UNIT_COMMAND_MARKERS.items()
    }


def check_temporal(unit_processes: Mapping[str, Sequence[doctor.DevProcess]]) -> Check:
    if not tcp_open(TEMPORAL_HOST, TEMPORAL_PORT):
        return Check("svc.temporal", Status.ERROR, f"server not reachable on :{TEMPORAL_PORT}", "hogli start")
    if not unit_processes.get(WORKER_UNIT):
        return Check(
            "svc.temporal",
            Status.ERROR,
            f"server up, but no worker for {TEMPORAL_TASK_QUEUE} in this checkout",
            "start the temporal-worker process (hogli start)",
        )
    return Check("svc.temporal", Status.OK, f"server up, worker running for {TEMPORAL_TASK_QUEUE}")


def process_started_at(process: doctor.DevProcess) -> float | None:
    try:
        return time.mktime(time.strptime(" ".join(process.start_time.split()), PROCESS_START_FORMAT))
    except ValueError:
        return None


def stale_env_files(started_at: float, modified_at: Mapping[str, float]) -> list[str]:
    return sorted(name for name, modified in modified_at.items() if modified > started_at)


def check_stale_processes(
    unit_processes: Mapping[str, Sequence[doctor.DevProcess]], layer_paths: Sequence[Path]
) -> Check:
    modified_at = {path.name: path.stat().st_mtime for path in layer_paths if path.is_file()}
    stale: list[str] = []
    for unit, processes in unit_processes.items():
        known = [moment for moment in map(process_started_at, processes) if moment is not None]
        if not known:
            continue
        edited = stale_env_files(min(known), modified_at)
        if edited:
            stale.append(f"{unit} (edited {', '.join(edited)})")
    if stale:
        return Check(
            "env.stale",
            Status.WARN,
            "env edited after start: " + "; ".join(stale),
            "restart those processes; for .env also run direnv reload first",
        )
    return Check("env.stale", Status.OK, "running processes saw the current env files")


def check_intent() -> Check:
    from hogli_commands.devenv.generator import get_generated_mprocs_path, load_devenv_config
    from hogli_commands.devenv.registry import create_mprocs_registry
    from hogli_commands.devenv.resolver import IntentResolver, load_intent_map

    saved = load_devenv_config(get_generated_mprocs_path())
    if saved is None:
        return Check("intent", Status.WARN, "no dev:setup config found", INTENT_FIX)
    try:
        resolved = IntentResolver(load_intent_map(), create_mprocs_registry()).resolve(
            saved.intents,
            include_units=saved.include_units,
            exclude_units=saved.exclude_units,
            skip_autostart=saved.skip_autostart,
            enable_autostart=saved.enable_autostart,
        )
    except (ValueError, FileNotFoundError) as error:
        return Check("intent", Status.WARN, f"could not resolve intents: {error}", INTENT_FIX)
    required = tuple(UNIT_COMMAND_MARKERS)
    missing = [unit for unit in required if unit not in resolved.units]
    if missing:
        return Check("intent", Status.ERROR, f"not started by your intents: {', '.join(missing)}", INTENT_FIX)
    manual = [unit for unit in required if unit in resolved.skip_autostart]
    if manual:
        summary = f"included but not auto-started: {', '.join(manual)}"
        return Check("intent", Status.WARN, summary, "start them in phrocs, or drop them from skip_autostart")
    return Check("intent", Status.OK, f"intents start {', '.join(required)}")


def sandbox_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in LOCAL_HOSTNAMES:
        return url
    port = f":{parsed.port}" if parsed.port else ""
    return parsed._replace(netloc=f"host.docker.internal{port}").geturl()


def sandbox_probe_targets(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    gateway_url = environ.get("SANDBOX_LLM_GATEWAY_URL")
    if gateway_url:
        targets.append(("llm-gateway", sandbox_url(gateway_url.rstrip("/")) + "/_liveness"))
    mcp_url = resolve_mcp_url(
        sandbox_mcp_url=environ.get("SANDBOX_MCP_URL"),
        mcp_server_url=environ.get("MCP_SERVER_URL") or MCP_SERVER_URL_DEFAULT,
    )
    if mcp_url:
        parsed = urlparse(mcp_url)
        targets.append(("mcp", f"{parsed.scheme}://{parsed.netloc}/health"))
    return targets


def sandbox_probe_script(targets: Sequence[tuple[str, str]]) -> str:
    probes = [
        f"curl --noproxy '*' -s -o /dev/null --max-time {SANDBOX_CURL_MAX_TIME_SECONDS} "
        f"-w {shlex.quote(name + ' %{http_code}' + chr(92) + 'n')} {shlex.quote(url)} &"
        for name, url in targets
    ]
    return " ".join([*probes, "wait"])


def unreachable_targets(output: str, names: Sequence[str]) -> list[str]:
    http_codes: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2:
            http_codes[parts[0]] = parts[1]
    failed: list[str] = []
    for name in names:
        http_code = http_codes.get(name)
        if http_code is None:
            failed.append(f"{name} (no response)")
        elif not http_code.startswith("2"):
            failed.append(f"{name} (http {http_code})")
    return failed


def reach_failure_status(failed_names: Sequence[str]) -> Status:
    if all(name in OPTIONAL_TARGETS for name in failed_names):
        return Status.WARN
    return Status.ERROR


def check_sandbox_reach(environ: Mapping[str, str]) -> Check:
    image = run_command(["docker", "image", "inspect", SANDBOX_BASE_IMAGE], COMMAND_TIMEOUT_SECONDS)
    if image is None or image.returncode != 0:
        return Check("sandbox.reach", Status.SKIPPED, f"docker down, or {SANDBOX_BASE_IMAGE} not built yet")

    targets = sandbox_probe_targets(environ)
    completed = run_command(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--add-host",
            "host.docker.internal:host-gateway",
            "--entrypoint",
            "sh",
            SANDBOX_BASE_IMAGE,
            "-c",
            sandbox_probe_script(targets),
        ],
        SANDBOX_PROBE_TIMEOUT_SECONDS,
    )
    if completed is None or completed.returncode != 0:
        return Check("sandbox.reach", Status.WARN, "probe container failed to run")
    names = [name for name, _ in targets]
    failed = unreachable_targets(completed.stdout, names)
    if failed:
        failed_names = [name for name in names if any(entry.startswith(f"{name} (") for entry in failed)]
        return Check(
            "sandbox.reach",
            reach_failure_status(failed_names),
            "unreachable from a sandbox container: " + ", ".join(failed),
            "check the svc.* results, then the SANDBOX_*_URL values",
        )
    return Check("sandbox.reach", Status.OK, "sandbox container reaches " + ", ".join(name for name, _ in targets))


def check_modal_auth(environ: Mapping[str, str]) -> Check:
    token_env = {key: environ[key] for key in MODAL_TOKEN_KEYS if key in environ}
    if len(token_env) < len(MODAL_TOKEN_KEYS) and not MODAL_CONFIG_PATH.is_file():
        return Check("modal.auth", Status.ERROR, "no Modal credentials in env or ~/.modal.toml", MODAL_TOKEN_FIX)
    completed = run_command(
        [sys.executable, "-m", "modal", "token", "info"],
        COMMAND_TIMEOUT_SECONDS,
        env={**os.environ, **token_env},
    )
    if completed is None:
        return Check("modal.auth", Status.WARN, "modal token info did not finish")
    if completed.returncode != 0:
        return Check("modal.auth", Status.ERROR, "Modal rejected the token, or Modal is unreachable", MODAL_TOKEN_FIX)
    source = "MODAL_TOKEN_* env" if len(token_env) == len(MODAL_TOKEN_KEYS) else "~/.modal.toml"
    return Check("modal.auth", Status.OK, f"token accepted ({source})")


def root_url(url: str | None, path: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def modal_targets(environ: Mapping[str, str]) -> list[tuple[str, str | None]]:
    gateway_url = environ.get("SANDBOX_LLM_GATEWAY_URL")
    mcp_url = resolve_mcp_url(
        sandbox_mcp_url=environ.get("SANDBOX_MCP_URL"),
        mcp_server_url=environ.get("MCP_SERVER_URL") or MCP_SERVER_URL_DEFAULT,
    )
    return [
        ("api", root_url(environ.get("SANDBOX_API_URL") or environ.get("SITE_URL"), "/_livez")),
        ("llm-gateway", gateway_url.rstrip("/") + "/_liveness" if gateway_url else None),
        ("mcp", root_url(mcp_url, "/health")),
    ]


def is_public(url: str | None) -> bool:
    return url is not None and urlparse(url).hostname not in NON_PUBLIC_HOSTNAMES


def check_modal_urls(targets: Sequence[tuple[str, str | None]]) -> Check:
    local = [name for name, url in targets if not is_public(url)]
    if local:
        summary = "Modal runs in the cloud and cannot reach these (unset or local): " + ", ".join(local)
        return Check("modal.urls", Status.ERROR, summary, TUNNEL_FIX)
    return Check("modal.urls", Status.OK, "api, llm-gateway and mcp have public URLs")


def tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found is not None:
        return found
    return str(TAILSCALE_APP_BINARY) if TAILSCALE_APP_BINARY.is_file() else None


def tailscale_json(binary: str, args: Sequence[str]) -> dict | None:
    completed = run_command([binary, *args, "--json"], COMMAND_TIMEOUT_SECONDS)
    if completed is None or completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def funnel_listeners(serve_status: Mapping, host: str) -> dict[int, int]:
    configs = [serve_status, *(serve_status.get("Foreground") or {}).values()]
    listeners: dict[int, int] = {}
    for config in configs:
        for key, allowed in (config.get("AllowFunnel") or {}).items():
            node, _, port = str(key).rpartition(":")
            if not allowed or node != host or not port.isdigit():
                continue
            handlers = ((config.get("Web") or {}).get(key) or {}).get("Handlers") or {}
            local_port = urlparse((handlers.get("/") or {}).get("Proxy") or "").port
            if local_port is not None:
                listeners[int(port)] = local_port
    return listeners


def funnel_local_ports(environ: Mapping[str, str]) -> dict[str, int]:
    return {
        "api": DJANGO_PORT_DEFAULT,
        "llm-gateway": int(environ.get("LLM_GATEWAY_PORT") or LLM_GATEWAY_PORT_DEFAULT),
        "mcp": local_mcp_port(environ),
    }


def funnel_fix(binary: str, host: str, local_ports: Mapping[str, int]) -> str:
    env_keys = {"api": "SANDBOX_API_URL", "llm-gateway": "SANDBOX_LLM_GATEWAY_URL", "mcp": "SANDBOX_MCP_URL"}
    commands: list[str] = []
    env_lines: list[str] = []
    for (name, local_port), public_port in zip(local_ports.items(), FUNNEL_PUBLIC_PORTS):
        url = f"https://{host}" if public_port == 443 else f"https://{host}:{public_port}"
        commands.append(f"{shlex.quote(binary)} funnel --https={public_port} http://127.0.0.1:{local_port}")
        env_lines.append(f"{env_keys[name]}={url}{'/mcp' if name == 'mcp' else ''}")
    return "\n".join(
        [
            f"one terminal each, started one at a time, foreground only ({FUNNEL_POLICY_DOC}):",
            *commands,
            "then replace these where they are set now (.env wins over .env.local):",
            *env_lines,
        ]
    )


def tunnel_problems(
    targets: Sequence[tuple[str, str | None]],
    host: str,
    listeners: Mapping[int, int],
    local_ports: Mapping[str, int],
) -> list[str]:
    problems: list[str] = []
    for name, url in targets:
        parsed = urlparse(url or "")
        if not parsed.hostname or not parsed.hostname.endswith(FUNNEL_HOST_SUFFIX):
            continue
        if parsed.hostname != host:
            problems.append(f"{name} points at {parsed.hostname}, not this machine")
            continue
        public_port = parsed.port or 443
        actual = listeners.get(public_port)
        if actual is None:
            problems.append(f"{name}: no Funnel on :{public_port}")
        elif actual != local_ports[name]:
            problems.append(f"{name}: Funnel :{public_port} goes to :{actual}, expected :{local_ports[name]}")
    return problems


def tailscale_node(binary: str) -> tuple[str | None, str | None]:
    status = tailscale_json(binary, ["status"])
    if status is None or status.get("BackendState") != "Running":
        return None, "Tailscale is not connected"
    node = status.get("Self") or {}
    granted = [*(node.get("Capabilities") or []), *(node.get("CapMap") or {})]
    if not any(str(capability) == "funnel" for capability in granted):
        return None, "this machine may not use Funnel (tailnet-policy.hujson nodeAttrs in posthog-cloud-infra)"
    return str(node.get("DNSName") or "").rstrip(".") or None, None


def check_modal_tunnel(targets: Sequence[tuple[str, str | None]], environ: Mapping[str, str]) -> Check:
    binary = tailscale_binary()
    if binary is None:
        return Check("modal.tunnel", Status.ERROR, "tailscale CLI not found", "install Tailscale and run tailscale up")
    host, problem = tailscale_node(binary)
    if host is None:
        return Check("modal.tunnel", Status.ERROR, problem or "no MagicDNS name for this machine", "tailscale up")
    local_ports = funnel_local_ports(environ)
    fix = funnel_fix(binary, host, local_ports)
    ngrok = [name for name, url in targets if (urlparse(url or "").hostname or "").endswith(NGROK_HOST_SUFFIXES)]
    if ngrok:
        summary = f"{', '.join(ngrok)} use ngrok; Tailscale Funnel is the approved replacement"
        return Check("modal.tunnel", Status.WARN, summary, fix)
    listeners = funnel_listeners(tailscale_json(binary, ["serve", "status"]) or {}, host)
    problems = tunnel_problems(targets, host, listeners, local_ports)
    if problems:
        return Check("modal.tunnel", Status.ERROR, "; ".join(problems), fix)
    return Check("modal.tunnel", Status.OK, f"Funnel serves the sandbox URLs on {host}")


def relay_problem(url: str) -> str | None:
    from products.posthog_ai.eval_harness.harness.tunnels import _public_ips, _relay_answers

    host = urlparse(url).hostname or ""
    try:
        addresses = _public_ips(host)
    except Exception:
        return "public DNS lookup failed"
    if not addresses:
        return "no public DNS record yet, a new Funnel can take minutes to publish"
    if not _relay_answers(addresses[0], host, urlparse(url).port or 443):
        return "public Funnel relay does not answer"
    return None


def public_url_problem(url: str) -> str | None:
    if not http_ok(url, PUBLIC_HTTP_TIMEOUT_SECONDS):
        return "no healthy answer"
    if (urlparse(url).hostname or "").endswith(FUNNEL_HOST_SUFFIX):
        return relay_problem(url)
    return None


def check_modal_reach(targets: Sequence[tuple[str, str | None]]) -> Check:
    public = [(name, url) for name, url in targets if url is not None and is_public(url)]
    if not public:
        return Check("modal.reach", Status.SKIPPED, "no public URLs to probe")
    with ThreadPoolExecutor(max_workers=len(public)) as pool:
        problems = list(pool.map(lambda target: public_url_problem(target[1]), public))
    failed = [(name, problem) for (name, _), problem in zip(public, problems) if problem is not None]
    if failed:
        return Check(
            "modal.reach",
            reach_failure_status([name for name, _ in failed]),
            "not reachable from Modal: " + "; ".join(f"{name} ({problem})" for name, problem in failed),
            "start Tailscale Funnel (see modal.tunnel) and the local service behind each URL",
        )
    return Check(
        "modal.reach", Status.OK, "reachable through the public URLs: " + ", ".join(name for name, _ in public)
    )


def check_database_state(repo_root: Path) -> list[Check]:
    completed = run_command(
        [sys.executable, str(repo_root / "manage.py"), "tasks_doctor"],
        DATABASE_CHECK_TIMEOUT_SECONDS,
    )
    if completed is None or completed.returncode != 0:
        detail = "timed out" if completed is None else (completed.stderr.strip().splitlines() or ["failed"])[-1]
        return [Check("db", Status.SKIPPED, f"manage.py tasks_doctor: {detail}")]
    try:
        rows = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return [Check("db", Status.SKIPPED, "manage.py tasks_doctor printed no JSON")]
    return [Check(row["id"], Status(row["status"]), row["summary"], row.get("fix")) for row in rows]


def run_isolated(check: Callable[[], Check]) -> Check:
    try:
        return check()
    except Exception as error:
        name = getattr(check, "func", check).__name__
        return Check(name, Status.ERROR, f"check crashed: {type(error).__name__}: {error}")


def run_all_checks(repo_root: Path, include_database: bool) -> list[Check]:
    layer_paths = env_layer_paths(repo_root)
    layers = load_env_layers(layer_paths, os.environ, secret_marker())
    provider = resolve_env_key("SANDBOX_PROVIDER", layers)
    backend = sandbox_backend(provider.value)
    results: list[Check] = [check_sandbox_provider(provider, backend), check_dotenv_loaded(layers)]
    results.extend(check_env_requirement(requirement, layers) for requirement in ENV_REQUIREMENTS)

    environ = effective_environ(layers)
    unit_processes = scan_unit_processes(repo_root)
    checks: list[Callable[[], Check]] = [
        check_intent,
        check_docker,
        partial(check_llm_gateway, environ),
        partial(check_mcp_server, environ),
        partial(check_temporal, unit_processes),
        partial(check_stale_processes, unit_processes, layer_paths),
    ]
    if backend == SANDBOX_BACKEND_DOCKER:
        checks.append(partial(check_sandbox_reach, environ))
    elif backend in MODAL_BACKENDS:
        targets = modal_targets(environ)
        results.append(check_modal_urls(targets))
        checks.extend(
            [
                partial(check_modal_auth, environ),
                partial(check_modal_tunnel, targets, environ),
                partial(check_modal_reach, targets),
            ]
        )
    else:
        results.append(Check("sandbox.reach", Status.SKIPPED, f"no checks for the {backend} provider yet"))

    with ThreadPoolExecutor(max_workers=len(checks) + 1) as pool:
        database = pool.submit(check_database_state, repo_root) if include_database else None
        results.extend(pool.map(run_isolated, checks))
        if database is not None:
            results.extend(database.result())
    return results


STATUS_COLORS = {Status.OK: "green", Status.WARN: "yellow", Status.ERROR: "red", Status.SKIPPED: "bright_black"}


def print_human(results: Sequence[Check]) -> None:
    click.echo("\nhogli tasks:doctor\n")
    for result in results:
        label = click.style(f" {result.status.value.upper()}", fg=STATUS_COLORS[result.status], bold=True)
        click.echo(f"{f'  {result.id} '.ljust(40, '.')}{label} ({result.summary})")
        if result.fix and result.status in (Status.WARN, Status.ERROR):
            first, *rest = result.fix.splitlines()
            click.echo(f"{'':>42}fix: {first}")
            for line in rest:
                click.echo(f"{'':>47}{line}")
    errors = sum(1 for result in results if result.status == Status.ERROR)
    warnings = sum(1 for result in results if result.status == Status.WARN)
    click.echo()
    if errors == 0 and warnings == 0:
        click.secho("  Ready for local task runs.", fg="green")
    else:
        click.secho(f"  {errors} error(s), {warnings} warning(s).", fg="red" if errors else "yellow")
    click.echo()


@click.command(
    name="tasks:doctor",
    help="Check that local task runs (sandboxes, wizard cloud runs) can work. Read-only.",
)
@click.option("--json", "as_json", is_flag=True, help="Print results as JSON for agents and scripts")
@click.option("--skip-db", is_flag=True, help="Skip the database checks (they boot Django, which is slow)")
def tasks_doctor(as_json: bool, skip_db: bool) -> None:
    results = run_all_checks(REPO_ROOT, include_database=not skip_db)
    if as_json:
        click.echo(json.dumps([result.to_json() for result in results], indent=2))
    else:
        print_human(results)
    if any(result.status == Status.ERROR for result in results):
        raise SystemExit(1)
