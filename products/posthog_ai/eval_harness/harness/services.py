from __future__ import annotations

import io
import os
import sys
import json
import time
import shutil
import signal
import asyncio
import hashlib
import logging
import secrets
import zipfile
import contextlib
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import InterfaceError, OperationalError, close_old_connections

import requests
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from posthog.storage.gateway_credential_cache import GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL

from products.posthog_ai.eval_harness.long_lived_subprocess import LongLivedSubprocessManager, SubprocessStartupError
from products.tasks.backend.facade.agents import (
    ENV_LOCAL_SKILLS_HOST_PATH,
    MCP_EXEC_SKILLS_FEATURE_FLAG,
    LocalSkillsCache,
)

from .ports import (
    AI_GATEWAY_PORT,
    AI_GATEWAY_REDIS_URL,
    MCP_PORT,
    PERSONHOG_REPLICA_PORT,
    PERSONHOG_ROUTER_PORT,
    SKILL_ARCHIVE_PORT,
)
from .providers import PreflightError

logger = logging.getLogger(__name__)

LONG_LIVED_SUBPROCESSES = LongLivedSubprocessManager()
_ZIP_FIXED_TIME = (2020, 1, 1, 0, 0, 0)

EVAL_AI_PRODUCT = "posthog_ai"
"""The gateway product eval tasks resolve to through their ``posthog_ai`` origin."""

AI_GATEWAY_EVAL_DATABASE = "ai_gateway_evals"
AI_GATEWAY_EVAL_CREDITS_USD = "10000"
_AI_GATEWAY_INTERNAL_TOKEN = secrets.token_urlsafe(32)
_AI_GATEWAY_CREDIT_GRANT_ID = secrets.token_hex(16)
AI_GATEWAY_CREDENTIAL_REFRESH_SECONDS = max(1, min(3600, GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL // 3))


def ai_gateway_repo() -> Path:
    """The local ``PostHog/ai-gateway`` clone, at the path ``bin/start-ai-gateway`` uses."""
    override = os.environ.get("AI_GATEWAY_REPO")
    return (Path(override).expanduser() if override else Path.home() / "Development" / "ai-gateway").resolve()


def _ai_gateway_binary() -> Path:
    return ai_gateway_repo() / ".run" / "eval-gateway"


def ensure_ai_gateway_binary() -> None:
    """Build the Go ai-gateway from the local clone, during preflight.

    The sandboxed agent's model calls go through the Go gateway, as they do in
    production for PostHog AI runs. The build is incremental, so only the first
    one after a pull is slow.
    """
    repo = ai_gateway_repo()
    if not (repo / "cmd" / "gateway").is_dir():
        raise PreflightError(
            f"No PostHog/ai-gateway clone at {repo}. The sandboxed agent's model calls go through it. "
            f"Run `git clone git@github.com:PostHog/ai-gateway.git {repo}`, "
            "or set AI_GATEWAY_REPO to the path of your clone."
        )
    if shutil.which("go") is None:
        raise PreflightError("`go` not found on PATH. The harness builds the ai-gateway from your clone.")

    logger.info("Building the ai-gateway from %s", repo)
    result = subprocess.run(
        ["go", "build", "-o", str(_ai_gateway_binary()), "./cmd/gateway"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10 * 60,
    )
    if result.returncode != 0:
        tail = "\n".join(((result.stdout or "") + (result.stderr or "")).splitlines()[-30:])
        raise PreflightError(f"Failed to build the ai-gateway (go exit {result.returncode}):\n{tail}")


def _ai_gateway_compose(*args: str) -> subprocess.CompletedProcess[str]:
    # PostHog's dev env exports COMPOSE_PROJECT_NAME=posthog, which outranks the
    # gateway compose file's own project name.
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ai_gateway_repo(),
        env={**os.environ, "COMPOSE_PROJECT_NAME": "ai-gateway"},
        check=True,
        capture_output=True,
        text=True,
        timeout=5 * 60,
    )


def start_ai_gateway() -> Callable[[], None]:
    """Start the Go ai-gateway on a non-default port, in resolver mode.

    It shares the Postgres and Valkey containers of the gateway repo's compose file
    with a dev-stack gateway, but uses its own database and Valkey DB index, so eval
    ledger rows and team policy blobs never mix with dev ones. The containers stay up
    after the run, as they do for ``bin/start-ai-gateway``.
    """
    _ai_gateway_compose("up", "-d", "--wait", "postgres", "valkey")
    exists = _ai_gateway_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname = '{AI_GATEWAY_EVAL_DATABASE}'",
    ).stdout.strip()
    if exists != "1":
        _ai_gateway_compose("exec", "-T", "postgres", "createdb", "-U", "postgres", AI_GATEWAY_EVAL_DATABASE)

    # A dev .env can carry AI_GATEWAY_* settings meant for Django or for a dev gateway.
    env = {key: value for key, value in os.environ.items() if not key.startswith("AI_GATEWAY_")}
    env.update(
        {
            "AI_GATEWAY_ENV": "dev",
            "AI_GATEWAY_AUTH_MODE": "resolver",
            "AI_GATEWAY_LISTEN_ADDR": f":{AI_GATEWAY_PORT}",
            "AI_GATEWAY_POSTGRES_DSN": f"postgres://postgres:postgres@localhost:5435/{AI_GATEWAY_EVAL_DATABASE}",
            "AI_GATEWAY_REDIS_URL": AI_GATEWAY_REDIS_URL,
            "AI_GATEWAY_INTERNAL_TOKEN": _AI_GATEWAY_INTERNAL_TOKEN,
            "AI_GATEWAY_ANTHROPIC_API_KEY": os.environ["LLM_GATEWAY_ANTHROPIC_API_KEY"],
            # The gateway refuses to boot without an OpenAI key, which only codex runs use.
            "AI_GATEWAY_OPENAI_API_KEY": os.environ.get("LLM_GATEWAY_OPENAI_API_KEY") or "unused",
            "AI_GATEWAY_LOG_FORMAT": "text",
            "AI_GATEWAY_LOG_LEVEL": "info",
        }
    )
    binary = _ai_gateway_binary()
    migrate = subprocess.run([str(binary), "migrate"], env=env, capture_output=True, text=True, timeout=120)
    if migrate.returncode != 0:
        raise SubprocessStartupError(f"ai-gateway ledger migration failed:\n{migrate.stdout}{migrate.stderr}")

    logger.info("Starting ai-gateway on port %d", AI_GATEWAY_PORT)
    _, stop = LONG_LIVED_SUBPROCESSES.start(
        name="ai-gateway",
        port=AI_GATEWAY_PORT,
        cmd=[str(binary)],
        cwd=ai_gateway_repo(),
        env=env,
        log_prefix="ai-gateway",
    )
    try:
        _wait_for_ai_gateway_ready()
    except Exception:
        stop()
        raise
    logger.info("ai-gateway ready on port %d", AI_GATEWAY_PORT)
    return stop


def _wait_for_ai_gateway_ready(timeout_seconds: float = 120) -> None:
    # The gateway listens before its model catalog is built. Until a provider listing
    # succeeds, /readyz answers 503 and /v1/models is empty. A bad provider key never gets past this.
    deadline = time.monotonic() + timeout_seconds
    body = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"http://localhost:{AI_GATEWAY_PORT}/readyz", timeout=5)
        except requests.RequestException as e:
            body = str(e)
        else:
            if response.status_code == 200:
                return
            body = response.text[:500]
        time.sleep(1)
    raise SubprocessStartupError(
        f"ai-gateway did not become ready in {timeout_seconds:.0f}s. Check the provider API keys. Last /readyz: {body}"
    )


def refresh_ai_gateway_mint_key(team_id: int, mint_key: str) -> None:
    try:
        call_command("setup_local_gateway_credential", "--phs", mint_key, "--team", str(team_id), stdout=io.StringIO())
        call_command("llm_gateway_team", "refresh", str(team_id), stdout=io.StringIO())
    finally:
        close_old_connections()


@contextlib.asynccontextmanager
async def maintain_ai_gateway_mint_key(team_id: int, mint_key: str) -> AsyncIterator[None]:
    async def refresh() -> None:
        expires_at = time.monotonic() + GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL
        while True:
            await asyncio.sleep(AI_GATEWAY_CREDENTIAL_REFRESH_SECONDS)
            retry_delay = 1.0
            while True:
                pending = asyncio.create_task(asyncio.to_thread(refresh_ai_gateway_mint_key, team_id, mint_key))
                try:
                    await asyncio.shield(pending)
                except asyncio.CancelledError:
                    await pending
                    raise
                except (InterfaceError, OperationalError, RedisConnectionError, RedisTimeoutError):
                    remaining = expires_at - time.monotonic()
                    if remaining <= 0:
                        raise
                    logger.warning("Gateway credential refresh failed; retrying", exc_info=True)
                    await asyncio.sleep(min(retry_delay, remaining))
                    retry_delay = min(retry_delay * 2, 60)
                else:
                    expires_at = time.monotonic() + GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL
                    break

    async with asyncio.TaskGroup() as group:
        task = group.create_task(refresh())
        try:
            yield
        finally:
            task.cancel()


def provision_ai_gateway_mint_key(team_id: int, *, agent_model: str) -> str:
    """Give the master demo team a ``phs_`` key the worker mints per-run tokens with.

    Each run's ``phe_`` token bills the minting team, so only the master team needs
    admission and spend headroom, not the per-case teams. Scoped tokens cannot
    use an overspend allowance, so the isolated eval ledger needs test credits.
    A model listing and one mint check the catalog and the credential, so a broken
    setup fails here and not as a model error in every case.
    """
    mint_key = f"phs_{secrets.token_hex(24)}"
    refresh_ai_gateway_mint_key(team_id, mint_key)

    base_url = f"http://localhost:{AI_GATEWAY_PORT}"
    credits = requests.post(
        f"{base_url}/internal/teams/{team_id}/credits",
        json={"amount_usd": AI_GATEWAY_EVAL_CREDITS_USD, "reason": "Local eval test credits"},
        headers={
            "Authorization": f"Bearer {_AI_GATEWAY_INTERNAL_TOKEN}",
            "Idempotency-Key": f"eval-{team_id}-{_AI_GATEWAY_CREDIT_GRANT_ID}",
            "X-Internal-Actor": "eval-harness",
        },
        timeout=10,
    )
    if not 200 <= credits.status_code < 300:
        raise SubprocessStartupError(f"ai-gateway refused eval test credits: HTTP {credits.status_code}")
    headers = {"Authorization": f"Bearer {mint_key}"}
    models = requests.get(f"{base_url}/v1/models", headers=headers, timeout=10)
    models.raise_for_status()
    model_ids = {entry.get("id") for entry in models.json().get("data", [])}
    if agent_model not in model_ids:
        raise SubprocessStartupError(f"The ai-gateway model catalog does not serve {agent_model!r}")
    mint = requests.post(
        f"{base_url}/v1/tokens",
        json={"cap_usd": "0.01", "ttl_seconds": 60, "product": EVAL_AI_PRODUCT, "obo": str(team_id)},
        headers=headers,
        timeout=10,
    )
    if not 200 <= mint.status_code < 300:
        raise SubprocessStartupError(
            f"ai-gateway refused to mint a run token: HTTP {mint.status_code} {mint.text[:300]}"
        )
    logger.info("ai-gateway mint key provisioned for team_id=%d", team_id)
    return mint_key


def start_mcp_server(
    live_server_url: str,
    skill_archive_url: str | None,
    *,
    exec_skills_enabled: bool,
) -> Callable[[], None]:
    """Start the MCP server as a subprocess for the eval session.

    Pointed at the in-process Django live server (which uses the test DB).
    Uses a non-default port to avoid conflicts with a running dev MCP server.

    Runs the Node-native Hono server via ``pnpm dev``. In production the
    Cloudflare Worker is now a proxy that forwards to a regional Hono
    deployment, so Hono is what real users hit.
    """
    if exec_skills_enabled and skill_archive_url is None:
        raise ValueError("skill_archive_url is required when exec skills are enabled")

    mcp_dir = Path(settings.BASE_DIR) / "services" / "mcp"
    if not (mcp_dir / "node_modules").exists():
        logger.info("Installing MCP server dependencies")
        subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=mcp_dir, check=True, capture_output=True)

    api_url = live_server_url

    # The Hono server reads config directly from process env — no wrangler
    # --var wiring needed. PORT picks the listen port; the dev script
    # bundles via esbuild then spawns Node on the bundle.
    env = {
        **os.environ,
        "POSTHOG_API_BASE_URL": api_url,
        "MCP_APPS_BASE_URL": f"http://localhost:{MCP_PORT}",
        "POSTHOG_MCP_APPS_ANALYTICS_BASE_URL": api_url,
        "NODE_ENV": "development",
        "PORT": str(MCP_PORT),
        "HOST": "0.0.0.0",
        # The MCP server evaluates feature flags via posthog-node, which is disabled
        # here (no POSTHOG_ANALYTICS_* config), so every flag would resolve false.
        # Force the selected behavior via the dev/test-only override seam
        # (honored only when NODE_ENV is explicitly development/test — set above).
        # revamped-py-notebooks gates the markdown notebook tools (create-markdown,
        # add-cell, update-cell, delete-cell, get, list-frames). It also *hides* the
        # legacy notebooks-create / notebooks-retrieve pair, which the two surfaces
        # being mutually exclusive makes unavoidable — an eval of the legacy tools
        # needs its own lever, not this one. mcp-exec-skills follows the run's
        # skill delivery mode. dashboard-widgets gates the widget batch tools that
        # the dashboard widget evals exercise.
        "FEATURE_FLAG_OVERRIDES": json.dumps(
            {
                "revamped-py-notebooks": True,
                "dashboard-widgets": True,
                MCP_EXEC_SKILLS_FEATURE_FLAG: exec_skills_enabled,
            }
        ),
    }

    # Never let a shell-level archive URL contaminate the bundled-skills baseline.
    env.pop("POSTHOG_MCP_SKILLS_URL", None)
    if exec_skills_enabled and skill_archive_url is not None:
        env["POSTHOG_MCP_SKILLS_URL"] = skill_archive_url

    logger.info(
        "Starting MCP server (Hono runtime) on port %d (API: %s, exec skills: %s)",
        MCP_PORT,
        api_url,
        exec_skills_enabled,
    )
    _, stop = LONG_LIVED_SUBPROCESSES.start(
        name="MCP server",
        port=MCP_PORT,
        cmd=["pnpm", "dev"],
        cwd=mcp_dir,
        env=env,
        log_prefix="mcp",
        # Cover the 60-second skill warmup, an in-flight download, and the development build.
        readiness_timeout=120 if exec_skills_enabled else 30,
    )

    logger.info("MCP server ready on port %d", MCP_PORT)
    return stop


def _personhog_target_dir(rust_dir: Path) -> Path:
    """Resolve where cargo drops the debug binaries.

    Defaults to ``rust/target``, but the flox dev shell exports
    ``CARGO_TARGET_DIR`` to a shared out-of-tree location, so honor it — otherwise
    the build lands there while we look under ``rust/target`` and never find it.
    """
    override = os.environ.get("CARGO_TARGET_DIR")
    return Path(override) if override else rust_dir / "target"


def ensure_personhog_binaries() -> None:
    """Build the personhog binaries the harness runs for person/group reads.

    The query API reads persons and groups exclusively through personhog (there is
    no ORM fallback), so the harness stands up ``personhog-replica`` +
    ``personhog-router`` from ``rust/`` against the test persons DB. Building here,
    during preflight, keeps the slow first compile off the async run path.
    """
    if shutil.which("cargo") is None:
        raise PreflightError(
            "`cargo` not found on PATH. The query API reads persons/groups through personhog, "
            "which the harness builds from rust/. Enter the flox dev shell or install the Rust toolchain."
        )

    rust_dir = Path(settings.BASE_DIR) / "rust"
    logger.info(
        "Building personhog binaries (first build can take several minutes; later builds are incremental no-ops)"
    )
    # Cargo runs in its own process group so a cancel can stop the rustc processes it
    # starts. A SIGINT to the harness alone stops Cargo and leaves the compilers running.
    build = subprocess.Popen(
        ["cargo", "build", "-p", "personhog-replica", "-p", "personhog-router"],
        cwd=rust_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        # The first build compiles the whole dependency tree; only later builds are
        # incremental no-ops. Keep the ceiling well clear of a cold compile.
        stdout, stderr = build.communicate(timeout=20 * 60)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(build.pid, signal.SIGKILL)
        build.wait()
        raise
    if build.returncode != 0:
        output = (stdout or "") + (stderr or "")
        tail = "\n".join(output.splitlines()[-30:])
        raise PreflightError(f"Failed to build personhog binaries (cargo exit {build.returncode}):\n{tail}")


def start_personhog() -> Callable[[], None]:
    """Start personhog-replica + personhog-router against the test persons DB.

    Django reads persons/groups only through personhog (no ORM fallback), so
    ``/query`` scorers read 0 unless the router is up and ``PERSONHOG_ADDR`` points
    at it. Both run as raw debug binaries — the read path needs no etcd, config
    server, or leader election (the router defaults to ``router_mode=replica``).
    """
    persons_url = os.environ.get("PERSONS_DB_WRITER_URL")
    if not persons_url:
        raise SubprocessStartupError(
            "PERSONS_DB_WRITER_URL is unset. personhog reads the seeded persons DB from it; "
            "start_personhog() must run after EvalDatabase.setup() has provisioned the test persons DB."
        )

    rust_dir = Path(settings.BASE_DIR) / "rust"
    target_dir = _personhog_target_dir(rust_dir)
    replica_bin = target_dir / "debug" / "personhog-replica"
    router_bin = target_dir / "debug" / "personhog-router"

    # METRICS_PORT=0 binds the Prometheus listener to an OS-assigned ephemeral port,
    # so the harness never collides with a dev stack's 9100/9101.
    logger.info("Starting personhog-replica on port %d", PERSONHOG_REPLICA_PORT)
    _, stop_replica = LONG_LIVED_SUBPROCESSES.start(
        name="personhog-replica",
        port=PERSONHOG_REPLICA_PORT,
        cmd=[str(replica_bin)],
        cwd=rust_dir,
        env={
            **os.environ,
            "PRIMARY_DATABASE_URL": persons_url,
            "GRPC_ADDRESS": f"127.0.0.1:{PERSONHOG_REPLICA_PORT}",
            "METRICS_PORT": "0",
            "RUST_LOG": "info",
        },
        log_prefix="personhog-replica",
    )

    logger.info("Starting personhog-router on port %d", PERSONHOG_ROUTER_PORT)
    try:
        _, stop_router = LONG_LIVED_SUBPROCESSES.start(
            name="personhog-router",
            port=PERSONHOG_ROUTER_PORT,
            cmd=[str(router_bin)],
            cwd=rust_dir,
            env={
                **os.environ,
                "REPLICA_URL": f"http://127.0.0.1:{PERSONHOG_REPLICA_PORT}",
                "GRPC_ADDRESS": f"127.0.0.1:{PERSONHOG_ROUTER_PORT}",
                "METRICS_PORT": "0",
                "RUST_LOG": "info",
            },
            log_prefix="personhog-router",
        )
    except Exception:
        stop_replica()
        raise

    logger.info("personhog ready (router on port %d)", PERSONHOG_ROUTER_PORT)

    def stop() -> None:
        try:
            stop_router()
        finally:
            stop_replica()

    return stop


def build_local_skills(*, set_bind_mount_env: bool) -> Path:
    """Build local skills once per run and return the built dist dir.

    Uses a content-hash cache so repeat runs skip the build when nothing has
    changed, keeping the base image stable while letting eval authors iterate on
    skills without rebuilding it.

    Depends on ``DEBUG=True`` being active while the skill renderer runs — some
    template helpers (e.g. HogQL example rendering) guard on that setting. The
    harness sets ``DEBUG=1`` in the environment before ``django.setup()``, so
    that ordering holds by the time this runs.

    A failed build raises instead of reusing an older ``dist/skills``: the cache
    would pin the new source hash onto the old output, and every later run would
    silently give the agent skills from another branch or edit.
    """
    cache = LocalSkillsCache()
    dist_dir = cache.ensure_built(allow_stale=False)
    if set_bind_mount_env:
        # Only ``DockerSandbox.create`` reads this to bind-mount the built skills.
        # Under the modal provider the locally built skills are instead baked into
        # the Modal image by the DEBUG ``from_dockerfile`` build, so setting it
        # there would be inert.
        os.environ[ENV_LOCAL_SKILLS_HOST_PATH] = str(dist_dir)
    return dist_dir


def package_local_skills_archive(skills_dir: Path, archive_path: Path | None = None) -> Path:
    """Create a deterministic MCP archive from the rendered working-tree skills."""
    destination = archive_path or skills_dir.parent / "skills.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(skills_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(skills_dir)
            if any(part.startswith(".") or part == "__pycache__" for part in relative_path.parts):
                continue
            info = zipfile.ZipInfo(relative_path.as_posix(), date_time=_ZIP_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, file_path.read_bytes())

    return destination


def start_skill_archive_server(archive_path: Path) -> tuple[str, Callable[[], None]]:
    """Serve the local skill archive to MCP under a content-addressed URL."""
    archive_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()[:16]
    archive_url = f"http://127.0.0.1:{SKILL_ARCHIVE_PORT}/{archive_path.name}?v={archive_digest}"
    logger.info("Starting skill archive server on port %d", SKILL_ARCHIVE_PORT)
    _, stop = LONG_LIVED_SUBPROCESSES.start(
        name="skill archive server",
        port=SKILL_ARCHIVE_PORT,
        cmd=[
            sys.executable,
            "-m",
            "http.server",
            str(SKILL_ARCHIVE_PORT),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(archive_path.parent),
        ],
        cwd=archive_path.parent,
        env={**os.environ},
        log_prefix="skill-archive",
    )
    return archive_url, stop


def stop_all_subprocesses() -> None:
    LONG_LIVED_SUBPROCESSES.stop_all()
