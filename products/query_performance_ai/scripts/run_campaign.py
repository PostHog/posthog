#!/usr/bin/env python3
"""In-sandbox driver for one autoresearch campaign.

Reads ``COORDINATOR_URL`` / ``COORDINATOR_TOKEN`` / ``CAMPAIGN_SQL`` /
``CAMPAIGN_QUERY_ID`` from the environment, preflights the coordinator,
locks the network down to the coordinator port, initializes the workspace,
and hands control to ``pi /skill::clickhouse-autoresearch-campaign``.

The coordinator decides whether to capture the baseline up front
(``capture_baseline_in_orchestrator=true``, currently the local-CH path)
or hand the agent a non-pre-initialized workspace and instructions to
rewrite the query first (test_cluster path with the team-1 prompt).
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
import urllib.parse
import urllib.request
from pathlib import Path

from .runtime import SCRIPTS_DIR, CampaignError, log, run
from .sandboxing import LockdownFailed, install_pi_toolchain, lockdown_network, prepare_pi_runtime

DEFAULT_WORKSPACE = Path("/tmp/autoresearch-campaign")

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _require_http_url(url: str) -> None:
    """URLs come from env vars; urllib also speaks ``file://``/``ftp://``."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise CampaignError(f"preflight URL scheme {scheme!r} not allowed (must be http/https): {url!r}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Sealing the redirect-bypass for `_require_http_url` (e.g. 302 → file://)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refusing to follow redirect to {newurl!r}", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def coordinator_request(
    url: str, token: str, *, method: str, path: str, body: dict | None = None, timeout_s: int = 15
) -> dict:
    endpoint = url.rstrip("/") + path
    _require_http_url(endpoint)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        endpoint,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise CampaignError(f"coordinator {method} {path} → {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise CampaignError(f"coordinator unreachable at {endpoint}: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise CampaignError(f"coordinator returned non-JSON: {raw[:300]!r}") from e


def preflight_coordinator(url: str, token: str) -> dict:
    """Confirm the coordinator answers `/v1/info` and can run a trivial SELECT.

    Returns the parsed `/v1/info` payload — `target`, `prompt_addendum`,
    `primary_metric`, `capture_baseline_in_orchestrator` — so callers can
    branch on them.
    """
    info = coordinator_request(url, token, method="GET", path="/v1/info")
    log(f"coordinator info: target={info.get('target')} primary_metric={info.get('primary_metric')}")
    select_one = coordinator_request(url, token, method="POST", path="/v1/run", body={"sql": "SELECT 1"}, timeout_s=30)
    log(f"coordinator preflight OK: SELECT 1 returned in {select_one.get('elapsed_ms')}ms")
    return info


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


def write_adapter_json(workspace: Path, *, coordinator_url: str, token: str) -> None:
    (workspace / "adapter.json").write_text(
        json.dumps(
            {
                "type": "coordinator",
                "url": coordinator_url,
                "token": token,
            },
            indent=2,
        )
        + "\n"
    )
    log(f"wrote adapter.json targeting {coordinator_url}")


def append_prompt_addendum(workspace: Path, addendum: str) -> None:
    """Inject the coordinator's prompt_addendum into autoresearch.md.

    pi-coding-agent reads autoresearch.md as durable per-campaign notes, and
    the SKILL.md tells it to read the file as part of setup. Putting the
    addendum at the top is the cheapest way to make sure it's seen before
    any baseline-related decision.
    """
    md_path = workspace / "autoresearch.md"
    if not md_path.is_file():
        log(f"WARNING: autoresearch.md missing at {md_path}; addendum dropped")
        return
    existing = md_path.read_text()
    md_path.write_text(addendum.rstrip() + "\n\n" + existing)
    log(f"prepended {len(addendum)}-byte prompt addendum to autoresearch.md")


def capture_baseline(workspace: Path) -> None:
    log("capturing baseline through the coordinator")
    run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "ch_capture_baseline.py"),
            "--workspace",
            str(workspace),
        ]
    )
    if not (workspace / "baseline" / "result.jsonl").exists():
        raise CampaignError("baseline capture left no result.jsonl behind")


def run_pi_campaign(workspace: Path) -> None:
    cwd = workspace.parent
    config_path = cwd / "autoresearch.config.json"
    if not config_path.is_file():
        raise CampaignError(f"missing {config_path}; campaign init must run first")

    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "<unset>")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    anthropic_key_state = "set" if anthropic_key else "<unset>"
    log(f"pi env: ANTHROPIC_BASE_URL={anthropic_base}")
    log(f"pi env: ANTHROPIC_API_KEY={anthropic_key_state}")

    log(f"invoking pi campaign (cwd={cwd}, --mode json for live event stream)")
    cmd = ["pi", "--mode", "json", "/skill::clickhouse-autoresearch-campaign"]
    log("$ " + " ".join(cmd) + f"  (cwd={cwd})")
    _run_pi_with_streaming_events(cmd, cwd)


def _run_pi_with_streaming_events(cmd: list[str], cwd: Path) -> None:
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
    """Emit only on terminal events — deltas and ``*_start`` duplicate ``*_end``."""
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        print(line, flush=True)  # noqa: T201
        return
    if not isinstance(event, dict):
        print(f"[pi] {line[:500]}", flush=True)  # noqa: T201
        return

    kind = event.get("type", "event")

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

    print(f"[pi:{kind}] {json.dumps(event, separators=(',', ':'))[:500]}", flush=True)  # noqa: T201


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--coordinator-url",
        default=os.environ.get("COORDINATOR_URL", ""),
        help="Base URL of the coordinator HTTP server (env: COORDINATOR_URL)",
    )
    parser.add_argument(
        "--coordinator-token",
        default=os.environ.get("COORDINATOR_TOKEN", ""),
        help="Random per-coordinator-run token (env: COORDINATOR_TOKEN)",
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
    if not args.coordinator_url:
        raise CampaignError("--coordinator-url (or COORDINATOR_URL) is required")
    if not args.coordinator_token:
        raise CampaignError("--coordinator-token (or COORDINATOR_TOKEN) is required")

    try:
        info = preflight_coordinator(args.coordinator_url, args.coordinator_token)

        # Lock down the network *before* the toolchain installs and *before*
        # any code that consumes secrets runs. On PI_BASE the toolchain is
        # pre-baked so this ordering costs nothing; on DEFAULT_BASE the
        # install would fail behind the lockdown — which is the right
        # failure mode (we should be running on PI_BASE).
        #
        # Lockdown failure is always fatal: the whole point of running pi
        # in a sandbox is that its egress is restricted to the coordinator,
        # so without the lockdown there's no point continuing.
        try:
            lockdown_network(args.coordinator_url)
        except LockdownFailed as e:
            raise CampaignError(f"network lockdown failed; refusing to run pi without it: {e}") from e

        install_pi_toolchain()
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
            coordinator_url=args.coordinator_url,
            token=args.coordinator_token,
        )

        addendum = info.get("prompt_addendum") or ""
        if addendum.strip():
            append_prompt_addendum(args.workspace, addendum)

        if info.get("capture_baseline_in_orchestrator", True):
            capture_baseline(args.workspace)
        else:
            log(
                "coordinator says capture_baseline_in_orchestrator=false; "
                "the agent will rewrite the query and capture the baseline itself"
            )

        run_pi_campaign(args.workspace)
        log("campaign completed")
        return 0
    except CampaignError as e:
        log(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
