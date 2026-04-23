#!/usr/bin/env python3
"""Drive a query-performance autoresearch campaign inside a posthog-sandbox-pi sandbox.

pi-coding-agent + pi-autoresearch are baked into the image. At runtime we
install only the in-repo ``pi-clickhouse-autoresearch`` plugin, apply two
patches (pi-ai gateway base URL, pi-autoresearch workspace-preservation),
init the campaign workspace, capture a baseline through the OAuth proxy,
and then hand control to ``pi /skill::clickhouse-autoresearch-campaign``.

Args accept env-var fallbacks so Task orchestration can inject them —
see argparse definitions below. Non-zero exit on failure.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import argparse
import tempfile
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

PRODUCT_DIR = Path(__file__).resolve().parent.parent
AUTORESEARCH_DIR = PRODUCT_DIR / "autoresearch"
SCRIPTS_DIR = AUTORESEARCH_DIR / "scripts"
DEFAULT_WORKSPACE = Path("/tmp/autoresearch-campaign")

# Where Dockerfile.sandbox-pi drops the pi-autoresearch extension (manual
# copy — not via `pi install`, so ~/.pi/agent/git/… doesn't exist).
BAKED_PI_AUTORESEARCH_EXTENSION = Path("/root/.pi/agent/extensions/pi-autoresearch")


class CampaignError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[campaign] {msg}", file=sys.stderr, flush=True)  # noqa: T201


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    result = subprocess.run(cmd, check=False, text=True, cwd=cwd)
    if result.returncode != 0:
        raise CampaignError(f"command failed with exit {result.returncode}: {' '.join(cmd)}")
    return result


def check_proxy_reachable(posthog_url: str, token: str) -> None:
    """Fail fast if the proxy/token is broken, before the 2-minute campaign kicks off."""
    endpoint = posthog_url.rstrip("/") + "/api/query_performance_proxy/execute-test/"
    body = json.dumps({"sql": "SELECT 1"}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise CampaignError(f"proxy preflight {e.code} at {endpoint}: {detail}") from e
    except urllib.error.URLError as e:
        raise CampaignError(f"proxy unreachable at {endpoint}: {e}") from e

    if not raw.strip():
        # 2xx with empty body typically means Caddy (:8010) ate the request —
        # flag it here instead of choking on json.loads below.
        raise CampaignError(
            f"proxy preflight got status={status} with an empty body from {endpoint}. "
            "If --posthog-url points at Caddy (:8010), switch to the Django dev server "
            "(:8000) — from the sandbox that's http://host.docker.internal:8000."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CampaignError(
            f"proxy preflight returned non-JSON response (status={status}) at {endpoint}: {raw[:300]!r}"
        ) from e

    log(f"proxy preflight OK ({data.get('elapsed_ms')}ms, query_id={data.get('query_id')})")


def prepare_pi_runtime() -> None:
    """Patch baked pi-ai / pi-autoresearch state and install the in-repo plugin."""
    _patch_pi_ai_anthropic_baseurl()
    _patch_pi_autoresearch_index_ts()

    plugin_dir = Path.home() / ".pi/packages/pi-clickhouse-autoresearch"
    if not plugin_dir.is_dir():
        log("installing local pi-clickhouse-autoresearch plugin")
        run(["pi", "install", str(AUTORESEARCH_DIR)])
    else:
        log("pi-clickhouse-autoresearch already installed")


def _patch_pi_autoresearch_index_ts() -> None:
    """Stop pi-autoresearch's between-experiment ``git clean -fd`` from
    wiping the lane/hypothesis/review markdown the agent just wrote.
    Idempotent — re-applying is a no-op because the marker is gone."""
    index_ts = BAKED_PI_AUTORESEARCH_EXTENSION / "index.ts"
    if not index_ts.is_file():
        log(f"pi-autoresearch index.ts not found at {index_ts}; skipping workspace-preservation patch")
        return
    preserve = " ".join(
        f"-e {name}"
        for name in (
            "runs lanes hypotheses reviews baseline runtime state.json "
            "campaign.json operator-hunches.md adapter.json suggestions.md"
        ).split()
    )
    contents = index_ts.read_text()
    patched = contents.replace(
        "git clean -fd 2>/dev/null",
        f"git clean -fd {preserve} 2>/dev/null",
    )
    if patched != contents:
        log(f"patched {index_ts.name} to preserve workspace dirs")
        index_ts.write_text(patched)


def _patch_pi_ai_anthropic_baseurl() -> None:
    """Rewrite pi-ai's hardcoded `"https://api.anthropic.com"` to our gateway.

    pi-ai reads `model.baseUrl` directly from its bundled `models.generated.js`
    and ignores `ANTHROPIC_BASE_URL`, so routing through the PostHog LLM
    gateway means patching that file. No-op if the file or env var is missing.
    """
    gateway_base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    if not gateway_base:
        return

    # npm's global install path is platform-dependent.
    candidates = [
        Path(
            "/usr/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@mariozechner/pi-ai/dist/models.generated.js"
        ),
        Path(
            "/usr/local/lib/node_modules/@mariozechner/pi-coding-agent/node_modules/@mariozechner/pi-ai/dist/models.generated.js"
        ),
    ]
    models_file = next((p for p in candidates if p.is_file()), None)
    if models_file is None:
        log("pi-ai models.generated.js not found; skipping baseUrl patch")
        return

    contents = models_file.read_text()
    marker = '"https://api.anthropic.com"'
    if marker not in contents:
        # Either already patched (our URL is present) or the file shape changed.
        if gateway_base in contents:
            log(f"pi-ai models.generated.js already points at {gateway_base}")
        else:
            log("pi-ai models.generated.js has unexpected shape; skipping patch")
        return

    patched = contents.replace(marker, f'"{gateway_base}"')
    occurrences = contents.count(marker)
    models_file.write_text(patched)
    log(
        f"patched pi-ai models.generated.js: {occurrences} Anthropic baseUrl occurrence(s) "
        f'rewritten to "{gateway_base}"'
    )


def init_campaign(workspace: Path, query_file: Path, *, query_id: str) -> None:
    log(f"initializing campaign at {workspace} (query_id={query_id})")
    run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "ch_campaign_init.py"),
            "--workspace",
            str(workspace),
            "--query-id",
            query_id,
            "--query-file",
            str(query_file),
            "--branch-name",
            f"autoresearch/{query_id}",
        ]
    )


def write_adapter_json(workspace: Path, *, posthog_url: str, token: str) -> None:
    (workspace / "adapter.json").write_text(
        json.dumps(
            {
                "type": "posthog_proxy",
                "url": posthog_url,
                "token": token,
            },
            indent=2,
        )
        + "\n"
    )
    log(f"wrote adapter.json targeting {posthog_url}")


def capture_baseline(workspace: Path) -> None:
    log("capturing baseline through the proxy")
    run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "ch_capture_baseline.py"),
            "--workspace",
            str(workspace),
        ]
    )
    if not (workspace / "baseline" / "result.tsv").exists():
        raise CampaignError("baseline capture left no result.tsv behind")


def run_pi_campaign(workspace: Path) -> None:
    """Run the LLM-driven campaign.

    ``cwd`` is the workspace's parent — that's where campaign init dropped
    ``autoresearch.config.json`` that pi reads. We log the inherited
    Anthropic env vars first so a 401 post-invocation is easy to triage:
    wrong env vs pi ignoring them.
    """
    cwd = workspace.parent
    config_path = cwd / "autoresearch.config.json"
    if not config_path.is_file():
        raise CampaignError(f"missing {config_path}; campaign init must run first")

    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "<unset>")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    # Bool-only — CodeQL flags even a short API-key prefix as clear-text logging.
    anthropic_key_state = "set" if anthropic_key else "<unset>"
    log(f"pi env: ANTHROPIC_BASE_URL={anthropic_base}")
    log(f"pi env: ANTHROPIC_API_KEY={anthropic_key_state}")

    # Preflight with pi's exact headers — isolates gateway-reject vs
    # pi-overrides-baseURL when pi later fails to talk to Anthropic.
    if anthropic_base != "<unset>" and anthropic_key:
        _preflight_anthropic_gateway(anthropic_base, anthropic_key)

    log(f"invoking pi campaign (cwd={cwd}, --mode json for live event stream)")
    cmd = ["pi", "--mode", "json", "/skill::clickhouse-autoresearch-campaign"]
    log("$ " + " ".join(cmd) + f"  (cwd={cwd})")
    _run_pi_with_streaming_events(cmd, cwd)


def _run_pi_with_streaming_events(cmd: list[str], cwd: Path) -> None:
    """Stream and pretty-print pi's JSON event lines as they arrive.

    Without --mode json pi only emits human output at turn boundaries, so
    the operator sees long silences. The schema is pi's, not ours — we
    label events by ``type`` and tolerate unknown shapes.
    """
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )
    assert process.stdout is not None
    try:
        for raw in process.stdout:
            _print_pi_event(raw.rstrip("\n"))
    finally:
        exit_code = process.wait()
    if exit_code != 0:
        raise CampaignError(f"pi exited with {exit_code}")


def _print_pi_event(line: str) -> None:
    """Pretty-print one pi event for the operator.

    Only emits on terminal events (``*_end``, turn headers, token/cost) —
    deltas and ``*_start`` duplicate what the matching ``*_end`` carries.
    """
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        # pi startup banner, or stdout from a tool pi shelled out to.
        print(line, flush=True)  # noqa: T201
        return
    if not isinstance(event, dict):
        print(f"[pi] {line[:500]}", flush=True)  # noqa: T201
        return

    kind = event.get("type", "event")

    # Scaffolding + per-chunk updates add no operator signal — the matching
    # *_end event carries the complete result cleanly.
    if kind in (
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "tool_execution_start",
        "tool_execution_update",
    ):
        return

    if kind == "session":
        print(f"[pi:session] id={str(event.get('id', ''))[:8]}", flush=True)  # noqa: T201
        return

    if kind == "message_start":
        msg = event.get("message") or {}
        if msg.get("role") == "assistant":
            model = msg.get("model") or "?"
            print(f"[pi:turn] model={model}", flush=True)  # noqa: T201
        return

    if kind == "message_end":
        msg = event.get("message") or {}
        if msg.get("role") != "assistant":
            return
        usage = msg.get("usage") or {}
        bits = []
        if tokens := usage.get("totalTokens"):
            bits.append(f"tokens={tokens}")
        cost = (usage.get("cost") or {}).get("total")
        if isinstance(cost, int | float) and cost > 0:
            bits.append(f"cost=${cost:.4f}")
        print("[pi:turn_end] " + " ".join(bits), flush=True)  # noqa: T201
        return

    if kind == "message_update":
        sub = event.get("assistantMessageEvent") or {}
        sub_type = sub.get("type", "")
        if sub_type == "thinking_end":
            content = sub.get("content") or ""
            print(f"[pi:thinking] {content[:800]}", flush=True)  # noqa: T201
            return
        if sub_type == "text_end":
            content = sub.get("content") or ""
            print(f"[pi:text] {content[:800]}", flush=True)  # noqa: T201
            return
        if sub_type == "toolcall_end":
            tc = sub.get("toolCall") or {}
            name = tc.get("name", "?")
            args = tc.get("arguments") or {}
            args_str = json.dumps(args, separators=(",", ":"))[:500]
            print(f"[pi:tool] {name}({args_str})", flush=True)  # noqa: T201
            return
        # *_start / *_delta events — the matching *_end carries the full content.
        return

    if kind == "tool_execution_end":
        name = event.get("toolName", "?")
        result = event.get("result") or {}
        content = result.get("content") or []
        preview = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    preview = item["text"]
                    break
        preview = preview.replace("\n", " ⏎ ")[:300]
        print(f"[pi:result] {name} -> {preview}", flush=True)  # noqa: T201
        return

    # Unknown event — dump compact JSON so we notice.
    print(f"[pi:{kind}] {json.dumps(event, separators=(',', ':'))[:500]}", flush=True)  # noqa: T201


def _preflight_anthropic_gateway(base_url: str, api_key: str) -> None:
    """POST a 1-token /v1/messages to base_url with x-api-key=api_key."""
    endpoint = base_url.rstrip("/") + "/v1/messages"
    body = json.dumps(
        {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    log(f"preflighting Anthropic-compat endpoint: {endpoint}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            log(f"gateway preflight OK (status={resp.status})")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        log(f"gateway preflight {e.code}: {detail}")
    except urllib.error.URLError as e:
        log(f"gateway unreachable at {endpoint}: {e}")


def print_summary(workspace: Path) -> None:
    print()  # noqa: T201
    log("===== campaign artifacts =====")
    for subdir in ("baseline", "runs", "runtime", "lanes", "hypotheses"):
        path = workspace / subdir
        if not path.exists():
            continue
        for entry in sorted(path.rglob("*")):
            if entry.is_file():
                print(f"  {entry.relative_to(workspace)} ({entry.stat().st_size} bytes)")  # noqa: T201
    print()  # noqa: T201
    last_run_path = workspace / "runtime" / "last_run.json"
    if last_run_path.exists():
        log("last run:")
        print(json.dumps(json.loads(last_run_path.read_text()), indent=2))  # noqa: T201


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--posthog-url",
        default=os.environ.get("POSTHOG_URL", ""),
        help="Base URL of the PostHog app (env: POSTHOG_URL)",
    )
    parser.add_argument(
        "--posthog-token",
        default=os.environ.get("POSTHOG_OAUTH_TOKEN", ""),
        help="Scoped OAuth access token with clickhouse_test_cluster_perf:test_read (env: POSTHOG_OAUTH_TOKEN)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(os.environ.get("WORKSPACE") or DEFAULT_WORKSPACE),
        help="Campaign workspace path (default: /tmp/autoresearch-campaign)",
    )
    parser.add_argument(
        "--sql",
        default=os.environ.get("CAMPAIGN_SQL"),
        help="Inline SQL for the campaign. Mutually exclusive with --sql-file. "
        "Defaults to a SELECT 1 smoke test when neither is provided.",
    )
    parser.add_argument(
        "--sql-file",
        type=Path,
        default=Path(os.environ["CAMPAIGN_SQL_FILE"]) if os.environ.get("CAMPAIGN_SQL_FILE") else None,
        help="Path to a file containing the SQL for the campaign.",
    )
    parser.add_argument(
        "--query-id",
        default=os.environ.get("CAMPAIGN_QUERY_ID", "smoke-select-one"),
        help='Campaign identifier (stored in campaign.json). Default: "smoke-select-one".',
    )
    return parser.parse_args(argv)


def _resolve_sql_file(args: argparse.Namespace) -> tuple[Path, bool]:
    """Return ``(path, is_temp)`` for the SQL to run.

    Precedence: --sql-file > --sql > default SELECT 1. The caller owns
    cleanup of the temporary file when ``is_temp`` is True.
    """
    if args.sql_file is not None:
        if args.sql is not None:
            raise CampaignError("--sql and --sql-file are mutually exclusive")
        if not args.sql_file.is_file():
            raise CampaignError(f"--sql-file does not exist: {args.sql_file}")
        return args.sql_file, False

    sql_text = args.sql if args.sql is not None else "SELECT 1"
    if not sql_text.endswith("\n"):
        sql_text += "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as tmp:
        tmp.write(sql_text)
        return Path(tmp.name), True


def main() -> int:
    args = parse_args(sys.argv[1:])
    if not args.posthog_url:
        raise CampaignError("--posthog-url (or POSTHOG_URL) is required")
    if not args.posthog_token:
        raise CampaignError("--posthog-token (or POSTHOG_OAUTH_TOKEN) is required")

    try:
        check_proxy_reachable(args.posthog_url, args.posthog_token)
        prepare_pi_runtime()

        log(f"resetting workspace {args.workspace}")
        if args.workspace.exists():
            shutil.rmtree(args.workspace)

        query_file, is_temp = _resolve_sql_file(args)
        try:
            init_campaign(args.workspace, query_file, query_id=args.query_id)
        finally:
            if is_temp:
                query_file.unlink(missing_ok=True)

        write_adapter_json(
            args.workspace,
            posthog_url=args.posthog_url,
            token=args.posthog_token,
        )
        capture_baseline(args.workspace)
        run_pi_campaign(args.workspace)
        print_summary(args.workspace)
        log("campaign completed")
        return 0
    except CampaignError as e:
        log(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
