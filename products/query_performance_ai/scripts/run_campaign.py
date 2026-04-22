#!/usr/bin/env python3
"""Drive a query-performance autoresearch campaign inside a PostHog sandbox.

Full loop:

1. Install the pi toolchain + pi-autoresearch + our local plugin.
2. Init a campaign workspace for the supplied SQL (defaults to ``SELECT 1``,
   i.e. a smoke test).
3. Write an ``adapter.json`` that routes queries through the PostHog
   OAuth-gated proxy (``/api/query_performance_proxy/execute-test/``).
4. Capture a baseline through the proxy.
5. Invoke ``pi /skill::clickhouse-autoresearch-campaign`` to kick off the
   actual LLM-driven campaign — this is the step that calls Anthropic via the
   PostHog LLM gateway, proposes candidate variants, and exercises the full
   orchestration surface.
6. Print artifacts.

Required arguments (all accept env-var fallbacks for easy injection from
Task orchestration):

* ``--posthog-url`` / ``POSTHOG_URL`` — base URL the sandbox uses to reach
  the PostHog app (in docker, typically ``http://host.docker.internal:8000``).
* ``--posthog-token`` / ``POSTHOG_OAUTH_TOKEN`` — scoped OAuth access token
  with ``clickhouse_perf:test_read`` scope.

Optional:

* ``--sql`` / ``--sql-file`` — the query under test. Without either, defaults
  to a ``SELECT 1`` smoke test.
* ``--query-id`` — campaign identifier, stored in ``campaign.json``.

Exits non-zero on any failure.
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
    """Round-trip a SELECT 1 through the proxy before doing anything else.

    If the proxy is unreachable or the token is rejected, fail fast with a
    useful error instead of discovering it three minutes into a pi install.
    """
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
        # A 2xx with no body almost always means the request went to a reverse
        # proxy that ate it — e.g. the PostHog dev Caddy on port 8010 is known
        # to return empty bodies for Docker-originated requests. Flag it loudly
        # rather than choking on json.loads a line later.
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


def install_pi_toolchain() -> None:
    if shutil.which("pi"):
        log(f"pi already installed: {shutil.which('pi')}")
    else:
        log("installing @mariozechner/pi-coding-agent globally via npm")
        run(["npm", "install", "-g", "@mariozechner/pi-coding-agent"])

    _patch_pi_ai_anthropic_baseurl()

    pi_autoresearch_dir = Path.home() / ".pi/agent/git/github.com/davebcn87/pi-autoresearch"
    if not pi_autoresearch_dir.is_dir():
        log("installing pi-autoresearch framework from git")
        run(["pi", "install", "https://github.com/davebcn87/pi-autoresearch"])

        # Preserve workspace dirs during log_experiment's auto-revert. Without
        # this, pi-autoresearch's default ``git clean -fd`` wipes untracked
        # artifacts between experiments. Same patch as the reference
        # dockerfile.
        index_ts = pi_autoresearch_dir / "extensions/pi-autoresearch/index.ts"
        if index_ts.is_file():
            log(f"patching {index_ts.name} to preserve workspace dirs")
            preserve = " ".join(
                f"-e {name}"
                for name in (
                    "runs lanes hypotheses reviews baseline runtime state.json "
                    "campaign.json operator-hunches.md adapter.json suggestions.md"
                ).split()
            )
            contents = index_ts.read_text()
            contents = contents.replace(
                "git clean -fd 2>/dev/null",
                f"git clean -fd {preserve} 2>/dev/null",
            )
            index_ts.write_text(contents)
    else:
        log("pi-autoresearch already installed")

    plugin_dir = Path.home() / ".pi/packages/pi-clickhouse-autoresearch"
    if not plugin_dir.is_dir():
        log("installing local pi-clickhouse-autoresearch plugin")
        run(["pi", "install", str(AUTORESEARCH_DIR)])
    else:
        log("pi-clickhouse-autoresearch already installed")


def _patch_pi_ai_anthropic_baseurl() -> None:
    """Rewrite pi-ai's hardcoded Anthropic baseUrl to point at our gateway.

    pi-coding-agent pulls in @mariozechner/pi-ai, which ships a static
    ``models.generated.js`` where every Anthropic model entry has
    ``baseUrl: "https://api.anthropic.com"``. ``ANTHROPIC_BASE_URL`` is
    ignored — the SDK reads ``model.baseUrl`` directly. So the only way
    to route pi through the PostHog LLM gateway is to rewrite that file
    after install.

    No-op if the file is missing (different pi version) or the env var is
    unset — we leave pi to use its default in those cases.
    """
    gateway_base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    if not gateway_base:
        return

    # Locate the bundled pi-ai models file. npm's global install path is
    # platform-dependent; try the common locations.
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
        # Already patched, or version shape changed. Check for our gateway URL
        # to disambiguate; if neither is present, log a warning.
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
    """Invoke the LLM-driven autoresearch campaign.

    ``pi`` picks up ``autoresearch.config.json`` from ``cwd``. We run it from
    the directory above the workspace because that's where campaign init
    dropped the config (matching pi-autoresearch's reference layout).

    Before invoking pi, we print the Anthropic env vars pi will inherit —
    the whole chain (gateway routing, token auth) depends on pi's Anthropic
    SDK picking up ``ANTHROPIC_BASE_URL``. If a 401 from Anthropic lands
    before these lines print, you know env inheritance broke. If the env
    vars print correctly but pi still ends up hitting ``api.anthropic.com``,
    pi is overriding the baseURL in its own SDK client construction.
    """
    cwd = workspace.parent
    config_path = cwd / "autoresearch.config.json"
    if not config_path.is_file():
        raise CampaignError(f"missing {config_path}; campaign init must run first")

    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "<unset>")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    anthropic_key_prefix = anthropic_key[:10] or "<unset>"
    log(f"pi env: ANTHROPIC_BASE_URL={anthropic_base}")
    log(f"pi env: ANTHROPIC_API_KEY={anthropic_key_prefix}...")

    # Preflight the gateway's Anthropic-compat endpoint with the exact same
    # headers pi's Anthropic SDK will use. Three-way diagnostic:
    #   success → pi's auth path works; if pi still fails, pi is overriding
    #             the baseURL or passing different headers.
    #   401/403 → gateway is reachable but rejecting our OAuth token; check
    #             scopes (need llm_gateway:read) or gateway's auth config.
    #   connection refused / timeout → gateway isn't reachable at that URL.
    if anthropic_base != "<unset>" and anthropic_key:
        _preflight_anthropic_gateway(anthropic_base, anthropic_key)

    log(f"invoking pi campaign (cwd={cwd}, --mode json for live event stream)")
    cmd = ["pi", "--mode", "json", "/skill::clickhouse-autoresearch-campaign"]
    log("$ " + " ".join(cmd) + f"  (cwd={cwd})")
    _run_pi_with_streaming_events(cmd, cwd)


def _run_pi_with_streaming_events(cmd: list[str], cwd: Path) -> None:
    """Run ``pi --mode json`` and pretty-print each JSON event as it arrives.

    Without --mode json, pi's human-format output only lands at turn
    boundaries — the operator sees a long silence between "invoking pi"
    and the final summary. --mode json emits every agent event (tool
    invocations, assistant messages, results) as a JSON line to stdout,
    so we can print them live.

    We don't try to parse the exact event schema — pi's is upstream and
    may change. We just label each event with its ``type``/``event`` key
    and dump a truncated JSON body. Non-JSON lines (e.g. subprocess
    output pi's Bash tool spawned) pass through verbatim.
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
    """Format one JSON event from ``pi --mode json`` for a human operator.

    Pi emits a verbose event stream: session/turn framing, then for every
    assistant turn a series of ``message_update`` events carrying deltas,
    then outer ``message_end`` and tool execution frames. Printing every
    event verbatim floods the terminal (each delta echoes the accumulated
    partial message including ``thinkingSignature`` base64 blobs).

    Strategy: only print on terminal events (``thinking_end``, ``text_end``,
    ``toolcall_end``, ``tool_execution_end``) plus per-turn headers and
    token/cost summaries. Skip deltas and start markers — they duplicate
    content the ``_end`` event will surface cleanly.
    """
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        # Non-JSON line (pi startup banner, subprocess output from a
        # tool pi invoked, etc.). Pass through so operators still see it.
        print(line, flush=True)  # noqa: T201
        return
    if not isinstance(event, dict):
        print(f"[pi] {line[:500]}", flush=True)  # noqa: T201
        return

    kind = event.get("type", "event")

    # Pi has lots of scaffolding events that add no operator signal.
    if kind in ("agent_start", "agent_end", "turn_start", "turn_end", "tool_execution_start"):
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
        # thinking_start / toolcall_start / *_delta — skip, the _end event
        # will carry the complete content.
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
        help="Scoped OAuth access token with clickhouse_perf:test_read (env: POSTHOG_OAUTH_TOKEN)",
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
        install_pi_toolchain()

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
