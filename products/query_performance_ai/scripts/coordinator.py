"""Local-only autoresearch coordinator.

Source slow queries from Metabase, open an HTTP server on localhost, and
fan a sandbox per query out via SandboxBase. Sandboxes are network-isolated
to ``localhost:$PORT`` (best-effort iptables; see run_campaign.py).

Run:

    python -m products.query_performance_ai.scripts.coordinator \\
        --target test_cluster \\
        --metabase-region us \\
        --query-log-database-id 142   # ClickHouse PROD US - OFFLINE \\
        --test-cluster-database-id 146 \\
        --team-id 2 --max-queries 5

Or just stand the server up for manual experimentation:

    python -m products.query_performance_ai.scripts.coordinator --target local --no-spawn
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import uuid
import shlex
import shutil
import signal
import argparse
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backends.base import ExecutionBackend
from .backends.local import LocalClickhouseBackend
from .backends.metabase import MetabaseBackend
from .server import ServerInfo, generate_token, make_server, serve_forever_in_thread
from .slow_queries import SlowQuery, fetch_available_columns, fetch_available_dictionaries, fetch_slow_queries

PRODUCT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = PRODUCT_DIR / "data" / "runs"
# Hard cap on concurrent sandboxes regardless of `--max-queries`. Each sandbox
# is ~2 GiB; this keeps total RAM around 20 GiB. Bigger fan-outs serialise
# behind the coordinator's `_query_lock` anyway, so more parallelism is just
# more idle agents waiting on the lock.
MAX_CONCURRENT_SANDBOXES = 10

# Live-sandbox registry: protects against orphan Docker containers when the
# coordinator is killed mid-run. SIGINT/SIGTERM handlers iterate this set and
# destroy each entry. Entries are added on `create()` success and removed
# after `destroy()`; the lock keeps the iteration in the signal handler safe
# vs. concurrent worker mutations.
_LIVE_SANDBOXES: dict[str, object] = {}
_LIVE_SANDBOXES_LOCK = threading.Lock()


def _log(msg: str) -> None:
    sys.stdout.write(f"[coordinator] {msg}\n")
    sys.stdout.flush()


# Word-bounded so we replace the bare `events` identifier (`FROM events`,
# `events.foo`, `events AS e`, `JOIN events ON`) without touching column
# names that contain the substring (`events_count`, `is_initial_query`).
_EVENTS_TABLE_RE = re.compile(r"\bevents\b")


def _rewrite_events_to_sharded(sql: str) -> str:
    return _EVENTS_TABLE_RE.sub("sharded_events", sql)


def _maybe_rewrite_events(query: SlowQuery, *, rewrite_events_to_sharded: bool) -> SlowQuery:
    if not rewrite_events_to_sharded:
        return query
    return SlowQuery(
        query_id=query.query_id,
        team_id=query.team_id,
        clickhouse_query=_rewrite_events_to_sharded(query.clickhouse_query),
        hogql_query=query.hogql_query,
        query_duration_ms=query.query_duration_ms,
        read_bytes=query.read_bytes,
        event_time=query.event_time,
    )


def _load_repo_dotenv() -> None:
    """Load `<repo>/.env` so the user doesn't have to source it manually.

    pi needs ``ANTHROPIC_API_KEY`` and the rest of the repo's dev env
    typically lives in ``.env``. ``override=False`` means anything the
    user already exported wins.
    """
    repo_root = _resolve_repo_root()
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    from dotenv import load_dotenv  # noqa: PLC0415 — keeps the dep on the optional path

    load_dotenv(env_path, override=False)


def _build_backend(args: argparse.Namespace) -> ExecutionBackend:
    if args.target == "test_cluster":
        if not args.metabase_region or not args.test_cluster_database_id:
            raise SystemExit(
                "--target test_cluster requires --metabase-region and --test-cluster-database-id "
                "(point the latter at the metabase database that runs candidate SQL on the test cluster, "
                "currently the team-1 cluster)"
            )
        return MetabaseBackend(region=args.metabase_region, database_id=args.test_cluster_database_id)
    if args.target == "local":
        return LocalClickhouseBackend(team_id=args.local_team_id)
    raise SystemExit(f"unknown --target: {args.target!r}")


def _pi_anthropic_env() -> dict[str, str]:
    """Forward the host's ``ANTHROPIC_API_KEY`` into the sandbox.

    pi-coding-agent talks to api.anthropic.com using ``ANTHROPIC_API_KEY``.
    The Claude-Code-managed ``ANTHROPIC_AUTH_TOKEN`` / ``ANTHROPIC_BASE_URL``
    pair is intentionally NOT forwarded: that token is scoped to Claude
    Code itself and pi-autoresearch isn't an authorized consumer of the
    LLM gateway. A direct first-party Anthropic key is required.

    Without ``ANTHROPIC_API_KEY`` set on the host, pi exits with
    "No API key found for unknown." — which is the right failure mode for
    "go set the key" to be the obvious next step.
    """
    out: dict[str, str] = {}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        out["ANTHROPIC_API_KEY"] = api_key
    return out


_DJANGO_READY = False


def _ensure_django_setup() -> None:
    """Idempotent Django bootstrap so SandboxBase can be imported.

    The sandbox module transitively imports ``products.tasks.backend.models``
    which references Django ORM models, so we *do* have to call
    ``django.setup()``. Side-channel env vars suppress the parts of
    PostHog's app-init that would otherwise connect to Postgres / Redis:

    - ``OPT_OUT_CAPTURE=1`` disables ``posthoganalytics`` self-capture
      (skips ``initialize_self_capture_api_token`` Postgres call in
      ``PostHogConfig.ready``).
    - ``SKIP_ASYNC_MIGRATIONS_SETUP=1`` skips the migration-readiness
      Postgres queries.
    - ``SANDBOX_PROVIDER=docker`` makes the module-level
      ``Sandbox = get_sandbox_class()`` in sandbox.py avoid importing
      ``modal_sandbox``.
    """
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    os.environ.setdefault("SANDBOX_PROVIDER", "docker")
    os.environ.setdefault("OPT_OUT_CAPTURE", "1")
    os.environ.setdefault("SKIP_ASYNC_MIGRATIONS_SETUP", "1")
    import django  # noqa: PLC0415

    django.setup()
    _DJANGO_READY = True


def _detect_current_branch(cwd: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv
            ["git", "branch", "--show-current"],
            check=False,
            text=True,
            capture_output=True,
            cwd=cwd,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    branch = (result.stdout or "").strip()
    return branch or None


def _spawn_one_sandbox(
    *,
    query: SlowQuery,
    coordinator_url: str,
    coordinator_token: str,
    keep_sandbox: bool,
    repo_root: Path,
    repository: str,
    branch: str,
) -> tuple[str, int]:
    """Provision a sandbox, run run_campaign.py inside, harvest, destroy.

    Returns ``(query_id, exit_code)``. Exceptions bubble up to the executor —
    we catch them at the top level so a single bad campaign doesn't tank the
    rest of the parallel fan.
    """
    # Lazy import: SandboxBase pulls in Django settings, structlog, etc.
    # Keeping it inside the worker means `--no-spawn` doesn't pay for it.
    _ensure_django_setup()
    from products.query_performance_ai.backend.harvest import harvest_artifacts  # noqa: PLC0415
    from products.tasks.backend.services.sandbox import (  # noqa: PLC0415
        SandboxConfig,
        SandboxTemplate,
        get_sandbox_class_for_backend,
    )

    sandbox_name = f"qp-autoresearch-{query.query_id[:12]}-{uuid.uuid4().hex[:6]}"
    sandbox_env: dict[str, str] = {
        "COORDINATOR_URL": coordinator_url,
        "COORDINATOR_TOKEN": coordinator_token,
        "CAMPAIGN_QUERY_ID": query.query_id,
    }
    sandbox_env.update(_pi_anthropic_env())
    config = SandboxConfig(
        name=sandbox_name,
        # PI_BASE bakes pi-coding-agent, the pi-autoresearch extension, and a
        # ClickHouse source snapshot at /opt/clickhouse — the agent uses the
        # source as a grounding context for hypotheses, and the toolchain
        # being pre-installed saves ~30-90s of npm + git per sandbox boot.
        template=SandboxTemplate.PI_BASE,
        default_execution_timeout_seconds=45 * 60,
        # Most of pi-coding-agent's work is LLM round-trips and ClickHouse
        # queries that go through the host's `/v1/run` — the in-sandbox process
        # set is small. 2 GiB is enough for git, node, and the campaign
        # workspace; CPU stays modest since heavy lifting is remote.
        memory_gb=2.0,
        cpu_cores=1.0,
        environment_variables=sandbox_env,
        metadata={"purpose": "query-performance-autoresearch", "query_id": query.query_id},
    )

    sandbox_cls = get_sandbox_class_for_backend("docker")
    _log(f"[{query.query_id}] provisioning sandbox {sandbox_name}")
    sandbox = sandbox_cls.create(config)
    with _LIVE_SANDBOXES_LOCK:
        _LIVE_SANDBOXES[sandbox.id] = sandbox

    output_dir = RUNS_DIR / query.query_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "input.json").write_text(
        json.dumps(
            {
                "query_id": query.query_id,
                "team_id": query.team_id,
                "query_duration_ms": query.query_duration_ms,
                "read_bytes": query.read_bytes,
                "event_time": query.event_time,
                "clickhouse_query": query.clickhouse_query,
                "hogql_query": query.hogql_query,
            },
            indent=2,
        )
        + "\n"
    )

    exit_code = 1
    try:
        # Hand the SQL across to the sandbox via env-file (not argv), so the
        # query string can't end up in `/proc/<pid>/cmdline` for a sibling
        # campaign to read.
        env_file = "/tmp/autoresearch-campaign.env"
        env_blob = (
            f"CAMPAIGN_SQL={shlex.quote(query.clickhouse_query)}\n"
            f"CAMPAIGN_QUERY_ID={shlex.quote(query.query_id)}\n"
            f"COORDINATOR_URL={shlex.quote(coordinator_url)}\n"
            f"COORDINATOR_TOKEN={shlex.quote(coordinator_token)}\n"
        )
        sandbox.write_file(env_file, env_blob.encode("utf-8"))

        # Clone the branch fresh inside the sandbox. We deliberately don't
        # bind-mount the host checkout: pi-coding-agent has full filesystem
        # access inside the sandbox, and a writable bind-mount means it can
        # (and did, during testing) modify the host's source tree mid-run.
        # A fresh clone gives the agent its own working copy whose
        # modifications stay sandboxed.
        org, repo = repository.lower().split("/", 1)
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"
        clone_url = f"https://github.com/{org}/{repo}.git"
        clone_cmd = (
            f"rm -rf {shlex.quote(repo_path)} && "
            f"mkdir -p {shlex.quote(f'/tmp/workspace/repos/{org}')} && "
            f"cd {shlex.quote(f'/tmp/workspace/repos/{org}')} && "
            f"git clone --depth 1 --single-branch --branch {shlex.quote(branch)} "
            f"{shlex.quote(clone_url)} {shlex.quote(repo)}"
        )
        _log(f"[{query.query_id}] cloning {repository}@{branch} into sandbox")
        clone_result = sandbox.execute(clone_cmd, timeout_seconds=5 * 60)
        if clone_result.exit_code != 0:
            stderr_tail = (clone_result.stderr or "")[-2000:]
            raise RuntimeError(f"git clone failed in sandbox (exit {clone_result.exit_code}):\n{stderr_tail}")

        command = (
            f"cd {shlex.quote(repo_path)} && "
            f"trap 'rm -f {shlex.quote(env_file)}' EXIT && "
            f"chmod 600 {shlex.quote(env_file)} && "
            f"set -a && . {shlex.quote(env_file)} && set +a && "
            f"python3 products/query_performance_ai/scripts/run_campaign.py 2>&1"
        )

        _log(f"[{query.query_id}] running run_campaign.py inside sandbox {sandbox.id}")
        stream = sandbox.execute_stream(command, timeout_seconds=45 * 60)
        log_path = output_dir / "campaign.log"
        with log_path.open("w") as log_file:
            for line in stream.iter_stdout():
                log_file.write(line)
                # Prefix with query_id so interleaved parallel logs are still readable.
                sys.stdout.write(f"[{query.query_id}] {line}")
                sys.stdout.flush()
        result = stream.wait()
        exit_code = result.exit_code

        if exit_code != 0:
            _log(f"[{query.query_id}] run_campaign.py exited {exit_code}")

        try:
            harvested = harvest_artifacts(
                sandbox,
                original_sql=query.clickhouse_query,
                query_id=query.query_id,
                campaign_stdout_tail=(result.stdout or "")[-4000:],
            )
            _write_artifacts(harvested, output_dir, repo_root=repo_root)
            _log(f"[{query.query_id}] artifacts written to {output_dir}")
        except Exception as e:  # noqa: BLE001
            _log(f"[{query.query_id}] harvest failed: {e}")
    finally:
        if keep_sandbox:
            _log(f"[{query.query_id}] --keep-sandboxes set; leaving {sandbox.id} running")
            with _LIVE_SANDBOXES_LOCK:
                _LIVE_SANDBOXES.pop(sandbox.id, None)
        else:
            try:
                sandbox.destroy()
            except Exception as e:  # noqa: BLE001
                _log(f"[{query.query_id}] sandbox destroy failed: {e}")
            finally:
                with _LIVE_SANDBOXES_LOCK:
                    _LIVE_SANDBOXES.pop(sandbox.id, None)

    return query.query_id, exit_code


def _destroy_all_live_sandboxes(reason: str) -> None:
    """Best-effort cleanup of every still-tracked sandbox.

    Called from SIGINT/SIGTERM handlers and from `main()`'s `finally`. Holds
    the registry lock for the snapshot but releases it before destroying
    so a slow `destroy()` doesn't block worker threads from deregistering.
    """
    with _LIVE_SANDBOXES_LOCK:
        snapshot = list(_LIVE_SANDBOXES.items())
        _LIVE_SANDBOXES.clear()
    if not snapshot:
        return
    _log(f"cleanup ({reason}): destroying {len(snapshot)} sandbox(es)")
    for sandbox_id, sandbox in snapshot:
        try:
            sandbox.destroy()
        except Exception as e:  # noqa: BLE001
            _log(f"  destroy {sandbox_id} failed: {e}")


def _install_signal_handlers() -> None:
    """SIGINT/SIGTERM → destroy live sandboxes, then exit non-zero.

    Without this, Ctrl-C leaves Docker containers running (each one happily
    burning RAM until its 45-minute timeout) and a future run sees orphans
    on `docker ps`.
    """

    def _handler(signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        _log(f"received {sig_name}; cleaning up sandboxes")
        _destroy_all_live_sandboxes(reason=sig_name)
        # 128 + signal number is the conventional shell exit code for
        # signal-killed processes.
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _write_artifacts(harvested, dest: Path, *, repo_root: Path) -> None:  # noqa: ANN001
    """Mirror what the deleted smoke command did, minus the smoke-output wipe."""
    output = dest / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "original.sql").write_text(harvested.original_sql.rstrip() + "\n")
    if harvested.best_sql:
        (output / "best.sql").write_text(harvested.best_sql.rstrip() + "\n")
    if harvested.baseline_metrics_json:
        (output / "baseline_metrics.json").write_text(harvested.baseline_metrics_json)
    if harvested.best_metrics_json:
        (output / "best_run_metrics.json").write_text(harvested.best_metrics_json)
    if harvested.last_run_json:
        (output / "last_run.json").write_text(harvested.last_run_json)
    if harvested.out_of_scope_suggestions:
        (output / "out-of-scope-suggestions.md").write_text(harvested.out_of_scope_suggestions)
    if harvested.campaign_stdout_tail:
        (output / "campaign_stdout_tail.log").write_text(harvested.campaign_stdout_tail)
    for sub, entries in (
        ("lanes", harvested.lanes),
        ("hypotheses", harvested.hypotheses),
        ("reviews", harvested.reviews),
    ):
        if not entries:
            continue
        sub_dir = output / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        for name, contents in entries:
            (sub_dir / name).write_text(contents)

    summary = {
        "query_id": harvested.query_id,
        "best_sql": harvested.best_sql,
        "baseline_metrics_json": harvested.baseline_metrics_json,
        "best_run_metrics_json": harvested.best_metrics_json,
        "lane_count": len(harvested.lanes),
        "hypothesis_count": len(harvested.hypotheses),
        "review_count": len(harvested.reviews),
        "repo_root": str(repo_root),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--target",
        choices=("test_cluster", "local"),
        required=True,
        help="Where the coordinator forwards candidate SQL.",
    )
    parser.add_argument(
        "--metabase-region", choices=("us", "eu"), help="Region for slow-query sourcing and (test_cluster) execution"
    )
    parser.add_argument(
        "--query-log-database-id",
        type=int,
        help=(
            "Metabase database id used to read system.query_log when sourcing slow queries. "
            "Prefer the OFFLINE cluster — it's not under user load. (US: 142, ClickHouse PROD US - OFFLINE.)"
        ),
    )
    parser.add_argument(
        "--test-cluster-database-id",
        type=int,
        help=(
            "Metabase database id the coordinator runs candidate SQL against when --target=test_cluster. "
            "Required only for --target=test_cluster."
        ),
    )
    parser.add_argument("--team-id", type=int, default=2, help="Team to source slow queries for (default: 2)")
    parser.add_argument(
        "--local-team-id",
        type=int,
        default=1,
        help=(
            "When --target=local, the team_id the dev ClickHouse contains data for. "
            "The agent's prompt addendum will instruct it to rewrite team_id predicates "
            "to this value before capturing the baseline. (default: 1, matching `bin/start`'s seed)"
        ),
    )
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--max-queries", type=int, default=5)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind-host", default="127.0.0.1", help="Host to bind the coordinator HTTP server to")
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        help="Just stand up the HTTP server; don't fetch slow queries or spawn sandboxes",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help=(
            "Fetch the slow queries that would be analyzed, print a summary to stdout, then exit. "
            "Skips the HTTP server, the sandbox provisioning, and the ANTHROPIC_API_KEY check. "
            "Useful for dry-running the column filter and inspecting candidate SQL before burning tokens."
        ),
    )
    parser.add_argument(
        "--rewrite-events-to-sharded",
        action="store_true",
        help=(
            "Rewrite every standalone `events` table reference in the slow query SQL to `sharded_events` "
            "before handing it to the agent. Workaround for test clusters whose `events` Distributed wrapper "
            "is leaner than `sharded_events`."
        ),
    )
    parser.add_argument(
        "--repository",
        default="PostHog/posthog",
        help="GitHub repository the sandbox clones from (default: %(default)s).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help=(
            "Branch the sandbox clones. Defaults to the current local git branch "
            "(falls back to 'master'). Must already exist on origin — sandboxes always pull from there."
        ),
    )
    parser.add_argument(
        "--test-query",
        action="store_true",
        help=(
            "Skip Metabase entirely and feed `SELECT 1, sleep(1)` as the campaign SQL. "
            "Useful as an end-to-end smoke: the agent should drop the sleep call within "
            "a couple of iterations. Mutually exclusive with --query-log-database-id."
        ),
    )
    parser.add_argument("--keep-sandboxes", action="store_true")
    return parser.parse_args(argv)


def _print_only(args: argparse.Namespace) -> int:
    """Dry-run: fetch the queries that would be analyzed and print them.

    Skips the HTTP server, sandbox provisioning, and ANTHROPIC_API_KEY check.
    Mirrors the production fetch+filter pipeline so the output is exactly
    the set of queries a real run would feed into sandboxes.
    """
    if not args.test_query:
        if not args.metabase_region or not args.query_log_database_id:
            raise SystemExit(
                "--print-only still needs --metabase-region and --query-log-database-id (or pass --test-query)"
            )
        if shutil.which("hogli") is None:
            raise SystemExit("`hogli` not on PATH; run from a flox environment with the workspace loaded")

    queries = _fetch_filtered_queries(args)
    _log(f"got {len(queries)} candidate queries (after filter)")

    if not queries:
        _log("no eligible slow queries found (ai_data_processing_approved=true). Nothing would run.")
        return 0

    print()  # noqa: T201 — print-only mode emits structured output to stdout
    for i, q in enumerate(queries, start=1):
        q = _maybe_rewrite_events(q, rewrite_events_to_sharded=args.rewrite_events_to_sharded)
        print(f"[{i}/{len(queries)}] query_id={q.query_id}")  # noqa: T201
        print(f"        team_id={q.team_id} duration={q.query_duration_ms}ms read_bytes={q.read_bytes}")  # noqa: T201
        print(f"        event_time={q.event_time}")  # noqa: T201
        preview = q.clickhouse_query.replace("\n", " ")[:200]
        print(f"        sql_preview: {preview}{'…' if len(q.clickhouse_query) > 200 else ''}")  # noqa: T201
        print()  # noqa: T201
    return 0


_TEST_QUERY_SQL = "SELECT 1, sleep(1)"


def _synthetic_test_query() -> SlowQuery:
    """A trivial slow query for end-to-end smoke runs (`--test-query`).

    `sleep(1)` adds a deterministic ~1s, so the agent's optimisation target
    is obvious (drop the sleep) and the campaign exercises the whole
    coordinator → sandbox → agent → coordinator round-trip without
    needing a real Metabase fetch.
    """
    return SlowQuery(
        query_id="test-query-smoke",
        team_id=0,
        clickhouse_query=_TEST_QUERY_SQL,
        hogql_query="",
        query_duration_ms=1000,
        read_bytes=0,
        event_time="",
    )


def _fetch_filtered_queries(args: argparse.Namespace) -> list[SlowQuery]:
    """Shared between --print-only and the real run: same filter, same source."""
    if args.test_query:
        # Bypass Metabase entirely. The synthetic query is well-formed
        # ClickHouse SQL with no team_id predicate, so the column /
        # dictionary filters and the team-rewrite prompt addendum are
        # all no-ops for it.
        _log("--test-query: skipping Metabase fetch and feeding `SELECT 1, sleep(1)` to the campaign")
        return [_synthetic_test_query()]

    available_columns: list[str] | None = None
    available_dictionaries: list[str] | None = None
    if args.target == "test_cluster":
        if not args.test_cluster_database_id:
            raise SystemExit("--target test_cluster needs --test-cluster-database-id (used to fetch available columns)")
        available_columns = fetch_available_columns(
            region=args.metabase_region,
            database_id=args.test_cluster_database_id,
        )
        _log(f"test cluster exposes {len(available_columns)} column names; filtering slow queries to subsets only")
        available_dictionaries = fetch_available_dictionaries(
            region=args.metabase_region,
            database_id=args.test_cluster_database_id,
        )
        _log(f"test cluster exposes {len(available_dictionaries)} dictionaries; filtering slow queries to subsets only")

    return fetch_slow_queries(
        region=args.metabase_region,
        database_id=args.query_log_database_id,
        team_id=args.team_id,
        lookback_hours=args.lookback_hours,
        limit=args.max_queries,
        available_columns=available_columns,
        available_dictionaries=available_dictionaries,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    _load_repo_dotenv()
    # Set DJANGO_SETTINGS_MODULE + SANDBOX_PROVIDER before any worker thread
    # might import `products.tasks.backend.services.sandbox`. Workers also
    # call this defensively (idempotent), but doing it here means the first
    # `import` from a worker thread doesn't race with the env-var write.
    _ensure_django_setup()

    if args.print_only:
        return _print_only(args)

    _install_signal_handlers()

    backend = _build_backend(args)

    info = ServerInfo(
        target=backend.target,
        prompt_addendum=backend.prompt_addendum(),
        primary_metric="latency_ms",
        # When the backend ships a prompt addendum, the agent has to act on
        # it (rewrite team_id predicates, etc.) before the baseline is
        # meaningful. So skip the orchestrator-side baseline whenever there's
        # any addendum text and let the agent capture it after rewriting.
        capture_baseline_in_orchestrator=not backend.prompt_addendum().strip(),
    )
    token = generate_token()
    server = make_server(host=args.bind_host, port=args.port, backend=backend, token=token, info=info)
    serve_forever_in_thread(server)
    actual_port = server.server_address[1]
    _log(f"HTTP server listening on http://{args.bind_host}:{actual_port} (backend={backend.name})")
    _log(f"coordinator token: {token}")

    if args.no_spawn:
        _log("--no-spawn: server will run until Ctrl-C")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            _log("shutting down")
        return 0

    if not args.test_query:
        if not args.metabase_region or not args.query_log_database_id:
            raise SystemExit(
                "--metabase-region and --query-log-database-id are required (or pass --test-query for a smoke run)"
            )
        if shutil.which("hogli") is None:
            raise SystemExit("`hogli` not on PATH; run from a flox environment with the workspace loaded")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. pi-autoresearch needs a first-party Anthropic key — "
            "Claude Code's gateway token (ANTHROPIC_AUTH_TOKEN) is intentionally NOT used.\n"
            "Export ANTHROPIC_API_KEY=<your key> before running the coordinator."
        )

    repo_root = _resolve_repo_root()
    branch = args.branch or _detect_current_branch(repo_root) or "master"
    _check_branch_on_remote(repo_root, args.repository, branch)

    if not args.test_query:
        _log(
            f"fetching up to {args.max_queries} slow queries from Metabase "
            f"({args.metabase_region} query-log-db={args.query_log_database_id} team={args.team_id} "
            f"lookback={args.lookback_hours}h)"
        )
    queries = [
        _maybe_rewrite_events(q, rewrite_events_to_sharded=args.rewrite_events_to_sharded)
        for q in _fetch_filtered_queries(args)
    ]
    if not queries:
        _log("no eligible slow queries found (ai_data_processing_approved=true). Nothing to do.")
        return 0
    _log(f"got {len(queries)} candidate queries; sandboxes will clone {args.repository}@{branch}")

    coordinator_url = f"http://host.docker.internal:{actual_port}"

    failures: list[str] = []
    try:
        with ThreadPoolExecutor(
            max_workers=min(len(queries), MAX_CONCURRENT_SANDBOXES),
            thread_name_prefix="qp-sandbox",
        ) as pool:
            futures = {
                pool.submit(
                    _spawn_one_sandbox,
                    query=q,
                    coordinator_url=coordinator_url,
                    coordinator_token=token,
                    keep_sandbox=args.keep_sandboxes,
                    repo_root=repo_root,
                    repository=args.repository,
                    branch=branch,
                ): q
                for q in queries
            }
            for fut in as_completed(futures):
                q = futures[fut]
                try:
                    qid, code = fut.result()
                    if code != 0:
                        failures.append(qid)
                except Exception as e:  # noqa: BLE001
                    _log(f"[{q.query_id}] FAILED: {e}")
                    failures.append(q.query_id)
    finally:
        # Belt-and-braces: even if the executor exits cleanly, anything that
        # registered itself but bypassed the per-worker `finally` (e.g.
        # uncaught exception during `create()`'s post-registration code)
        # still gets cleaned up here. With `--keep-sandboxes` the registry
        # is empty by this point because the worker pops itself.
        _destroy_all_live_sandboxes(reason="main-exit")

    if failures:
        _log(f"completed with {len(failures)} failed campaign(s): {', '.join(failures)}")
        return 1
    _log("all campaigns completed")
    return 0


def _resolve_repo_root() -> Path:
    """Walk up from the product dir until we find the repo root marker."""
    candidate = PRODUCT_DIR
    for _ in range(8):
        if (candidate / "manage.py").is_file() and (candidate / "products").is_dir():
            return candidate
        candidate = candidate.parent
    raise SystemExit(
        "could not locate the posthog repo root (looked for manage.py + products/). "
        "Run the coordinator from inside the posthog checkout."
    )


def _check_branch_on_remote(repo_root: Path, repository: str, branch: str) -> None:
    """The sandbox clones from origin, so a missing branch fails mid-campaign.

    Fail loud here instead. Local-vs-origin SHA drift is only a warning —
    the sandbox will pull origin's snapshot, not the local one.
    """
    try:
        ls_remote = subprocess.run(  # noqa: S603 — fixed argv
            ["git", "ls-remote", "--heads", "origin", branch],
            check=False,
            text=True,
            capture_output=True,
            cwd=repo_root,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _log(f"warning: couldn't check whether {branch!r} exists on origin (git unavailable)")
        return
    if ls_remote.returncode != 0 or not ls_remote.stdout.strip():
        raise SystemExit(
            f"branch {branch!r} doesn't exist on origin/{repository}. The sandbox clones from origin, "
            f"so it can't check out this branch. Push it first:\n"
            f"    git push -u origin {branch}\n"
            f"or rerun with --branch pointing at a branch that already exists on origin."
        )
    try:
        local = subprocess.run(  # noqa: S603 — fixed argv
            ["git", "rev-parse", branch],
            check=False,
            text=True,
            capture_output=True,
            cwd=repo_root,
            timeout=5,
        )
        remote_sha = ls_remote.stdout.split()[0]
        if local.returncode == 0 and local.stdout.strip() != remote_sha:
            _log(
                f"warning: local '{branch}' differs from origin/{branch} — sandboxes will clone origin's "
                "snapshot. `git push` to publish local commits."
            )
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
