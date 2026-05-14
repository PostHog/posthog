"""Build + run helpers for orchestra user deployments.

The deployment flow is:
    1. extract_code_archive(team_id, code_version, archive_bytes)
       writes the uploaded zip's contents to a per-build workspace dir.
    2. build_user_image(team_id, code_version, workspace_dir)
       writes a tiny Dockerfile inside workspace_dir, then `docker build`.
    3. run_user_container(team_id, code_version, image_name, modules, task_queue)
       `docker run -d` with the env vars the runtime expects.
    4. stop_container(container_id) once the deployment finishes draining.

The runtime image (posthog/orchestra-runtime) is built once by
bin/build-orchestra-runtime and contains the engine + a thin entrypoint.
"""

from __future__ import annotations

import io
import shutil
import logging
import zipfile
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from django.conf import settings

logger = logging.getLogger("orchestra.build")


class OrchestraBuildError(RuntimeError):
    """Raised when an external command (docker / zip) fails."""


@dataclass(frozen=True)
class BuildResult:
    image_name: str
    workspace_dir: Path
    modules: list[str]


def _workspace_for(team_id: int, code_version: str) -> Path:
    base = Path(settings.ORCHESTRA_BUILD_DIR)
    return base / f"team_{team_id}" / f"v_{code_version[:12]}"


def _dockerfile_for_user_image(modules: list[str]) -> str:
    base = settings.ORCHESTRA_RUNTIME_IMAGE
    modules_env = ",".join(modules)
    # USER_CODE_MODULES is also injected via `docker run -e` so this baked-in
    # value is a fallback for operators who run the image manually.
    return f"FROM {base}\nCOPY user_code/ /user-code/\nENV USER_CODE_MODULES={modules_env}\n"


def _safe_image_tag(team_id: int, code_version: str) -> str:
    short = code_version[:12]
    return f"orchestra-user:team-{team_id}-{short}"


def _discover_modules(user_code_root: Path) -> list[str]:
    """Find importable .py files at the user_code root (non-recursive into packages).

    For the MVP, treat every top-level `*.py` file (excluding __init__.py and
    __main__.py) as an importable module by its base name. Packages (directories
    with __init__.py) are also picked up. The user's archive should sit flat at
    the root — no nested src/ layout.
    """
    modules: list[str] = []
    for entry in sorted(user_code_root.iterdir()):
        if entry.is_dir():
            if (entry / "__init__.py").exists():
                modules.append(entry.name)
        elif entry.suffix == ".py" and entry.name not in ("__init__.py", "__main__.py"):
            modules.append(entry.stem)
    return modules


def extract_code_archive(*, team_id: int, code_version: str, archive: bytes | io.BytesIO) -> Path:
    """Unpack the uploaded zip into the per-build workspace and return the user_code root."""
    workspace = _workspace_for(team_id, code_version)
    if workspace.exists():
        shutil.rmtree(workspace)
    user_code_root = workspace / "user_code"
    user_code_root.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO(archive) if isinstance(archive, bytes) else archive
    try:
        with zipfile.ZipFile(buf, "r") as zf:
            # Reject zip-slip — refuse any member that resolves outside user_code_root.
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = (user_code_root / info.filename).resolve()
                if not str(target).startswith(str(user_code_root.resolve())):
                    raise OrchestraBuildError(f"unsafe zip member: {info.filename}")
            zf.extractall(user_code_root)
    except zipfile.BadZipFile as e:
        raise OrchestraBuildError(f"invalid zip archive: {e}") from e

    return user_code_root


def build_user_image(*, team_id: int, code_version: str, user_code_root: Path) -> BuildResult:
    """Render a Dockerfile next to the extracted code and `docker build` it."""
    workspace = user_code_root.parent
    modules = _discover_modules(user_code_root)
    if not modules:
        raise OrchestraBuildError(
            "no Python modules found at the root of the archive — drop *.py files or packages at the top level"
        )

    dockerfile = workspace / "Dockerfile"
    dockerfile.write_text(_dockerfile_for_user_image(modules))

    image_name = _safe_image_tag(team_id, code_version)
    cmd = ["docker", "build", "-t", image_name, "-f", str(dockerfile), str(workspace)]
    logger.info("building user image: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise OrchestraBuildError(f"docker build failed:\n{e.stderr}") from e

    return BuildResult(image_name=image_name, workspace_dir=workspace, modules=modules)


def _container_dsn() -> str:
    """The DSN to inject into user containers — same as ORCHESTRA_DSN but with
    localhost/127.0.0.1 rewritten to host.docker.internal so the container can
    reach the host's Postgres.
    """
    override = getattr(settings, "ORCHESTRA_CONTAINER_DSN", "")
    if override:
        return override

    parsed = urlparse(settings.ORCHESTRA_DSN)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        netloc = parsed.netloc.replace(parsed.hostname, "host.docker.internal", 1)
        return urlunparse(parsed._replace(netloc=netloc))
    return settings.ORCHESTRA_DSN


def run_user_container(
    *,
    team_id: int,
    code_version: str,
    image_name: str,
    modules: list[str] | None,
    task_queue: str,
) -> str:
    """`docker run -d` the user image and return the container id.

    When `modules` is None or empty, USER_CODE_MODULES is expected to be baked
    into the image (via the per-deploy Dockerfile generated by bin/deploy-orchestra).
    """
    cmd = [
        "docker",
        "run",
        "-d",
        "--add-host=host.docker.internal:host-gateway",
        "-e",
        f"DATABASE_URL={_container_dsn()}",
        "-e",
        f"TASK_QUEUE={task_queue}",
        "--label",
        f"posthog.team_id={team_id}",
        "--label",
        f"posthog.code_version={code_version}",
        "--label",
        "posthog.product=orchestra",
    ]
    if modules:
        cmd.extend(["-e", f"USER_CODE_MODULES={','.join(modules)}"])
    cmd.append(image_name)
    logger.info("running user container: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise OrchestraBuildError(f"docker run failed:\n{e.stderr}") from e
    return result.stdout.strip()


def stop_container(container_id: str, *, timeout_seconds: int = 30) -> None:
    """Best-effort `docker stop` + `docker rm`. Logs and swallows errors."""
    if not container_id:
        return
    try:
        subprocess.run(
            ["docker", "stop", "--time", str(timeout_seconds), container_id],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("docker stop %s failed: %s", container_id, e.stderr.strip())
    try:
        subprocess.run(
            ["docker", "rm", container_id],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("docker rm %s failed: %s", container_id, e.stderr.strip())
