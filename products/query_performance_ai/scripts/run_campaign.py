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

PRODUCT_DIR = Path(__file__).resolve().parent.parent
AUTORESEARCH_DIR = PRODUCT_DIR / "autoresearch"
SCRIPTS_DIR = AUTORESEARCH_DIR / "scripts"
DEFAULT_WORKSPACE = Path("/tmp/autoresearch-campaign")

# Bumping these requires a fresh smoke run — `_patch_pi_ai_anthropic_baseurl`
# is sensitive to pi-ai's bundle shape at this exact version.
PI_CODING_AGENT_VERSION = "0.68.1"
PI_AUTORESEARCH_COMMIT = "56e9f2ec6f0dc6f9997126e4f1d8a4223de2a534"

# Layout the dedicated PI_BASE image bakes; `install_pi_toolchain` reproduces
# it when running on DEFAULT_BASE.
BAKED_PI_AUTORESEARCH_EXTENSION = Path("/root/.pi/agent/extensions/pi-autoresearch")


class CampaignError(RuntimeError):
    pass


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


def log(msg: str) -> None:
    print(f"[campaign] {msg}", file=sys.stderr, flush=True)  # noqa: T201


def _atomic_write(path: Path, contents: str) -> None:
    """Temp-file + rename: a SIGKILL mid-write leaves the original intact."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(contents)
    os.replace(tmp, path)


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    result = subprocess.run(cmd, check=False, text=True, cwd=cwd)
    if result.returncode != 0:
        raise CampaignError(f"command failed with exit {result.returncode}: {' '.join(cmd)}")
    return result


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


class LockdownFailed(CampaignError):
    """Raised when the iptables lockdown can't be applied.

    Callers decide whether to treat this as fatal — when an Anthropic API
    key is in the sandbox env, we treat the failure as fatal so we never
    let pi-coding-agent run with both the key in env *and* unrestricted
    egress.
    """


def lockdown_network(coordinator_url: str) -> None:
    """iptables OUTPUT-DROP except localhost + the coordinator port.

    Requires NET_ADMIN, `iptables` on PATH, and the coordinator URL
    hostname must resolve. Raises :class:`LockdownFailed` on any
    precondition failure or rule error so the caller can decide to fail
    the campaign (correct when ANTHROPIC_API_KEY is in env).
    """
    parsed = urllib.parse.urlparse(coordinator_url)
    port = parsed.port
    if not port:
        raise LockdownFailed(
            f"coordinator URL has no explicit port: {coordinator_url!r} — refusing to lock down without a target"
        )
    # `host.docker.internal` resolves to the gateway via `--add-host`; resolve
    # it once so the rule pins the IP rather than depending on DNS later.
    try:
        gateway_ip = subprocess.check_output(  # noqa: S603
            ["getent", "hosts", parsed.hostname or "host.docker.internal"],
            text=True,
            timeout=5,
        ).split()[0]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, IndexError) as e:
        raise LockdownFailed(f"could not resolve {parsed.hostname!r}: {e}") from e

    rules = [
        # Allow loopback (the agent's own helpers may bind to 127.0.0.1).
        ["iptables", "-I", "OUTPUT", "1", "-o", "lo", "-j", "ACCEPT"],
        # Allow returning bytes for connections we initiated.
        ["iptables", "-I", "OUTPUT", "2", "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
        # Allow only the coordinator port at the gateway IP.
        ["iptables", "-I", "OUTPUT", "3", "-d", gateway_ip, "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"],
        # Drop everything else.
        ["iptables", "-P", "OUTPUT", "DROP"],
    ]
    for argv in rules:
        try:
            subprocess.run(argv, check=True, text=True, capture_output=True, timeout=5)  # noqa: S603
        except FileNotFoundError as e:
            raise LockdownFailed("iptables binary missing in sandbox image") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            if "Operation not permitted" in stderr or "Permission denied" in stderr:
                raise LockdownFailed("iptables refused (NET_ADMIN not granted to this sandbox)") from e
            raise LockdownFailed(f"iptables rule failed ({argv[-1]}): {stderr}") from e
    log(f"network locked down: only {gateway_ip}:{port} reachable")


def install_pi_toolchain() -> None:
    """No-op once PI_BASE (#55821) lands; until then DEFAULT_BASE pays a
    ~30-90s install per sandbox."""
    pi_already_installed = shutil.which("pi") is not None
    extension_present = BAKED_PI_AUTORESEARCH_EXTENSION.is_dir()
    if pi_already_installed and extension_present:
        log(f"pi toolchain pre-installed (pi @ {shutil.which('pi')}, extension at {BAKED_PI_AUTORESEARCH_EXTENSION})")
        return

    if not pi_already_installed:
        log(f"installing pi-coding-agent@{PI_CODING_AGENT_VERSION} via npm (global)")
        run(
            [
                "npm",
                "install",
                "-g",
                f"@mariozechner/pi-coding-agent@{PI_CODING_AGENT_VERSION}",
            ]
        )

    if not extension_present:
        with tempfile.TemporaryDirectory(prefix="pi-autoresearch-src-") as tmpdir:
            src_root = Path(tmpdir) / "pi-autoresearch"
            log(f"cloning pi-autoresearch@{PI_AUTORESEARCH_COMMIT[:8]} → {src_root}")
            run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "https://github.com/davebcn87/pi-autoresearch.git",
                    str(src_root),
                ]
            )
            run(["git", "checkout", "--quiet", PI_AUTORESEARCH_COMMIT], cwd=src_root)

            ext_src = src_root / "extensions" / "pi-autoresearch"
            if not ext_src.is_dir():
                raise CampaignError(
                    f"pi-autoresearch upstream missing {ext_src.relative_to(src_root)} at pinned commit"
                )
            BAKED_PI_AUTORESEARCH_EXTENSION.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ext_src, BAKED_PI_AUTORESEARCH_EXTENSION)
            log(f"copied extension files to {BAKED_PI_AUTORESEARCH_EXTENSION}")

            skills_src = src_root / "skills"
            if skills_src.is_dir():
                skills_dst = Path("/root/.pi/agent/skills")
                skills_dst.mkdir(parents=True, exist_ok=True)
                for skill_dir in skills_src.iterdir():
                    if skill_dir.is_dir():
                        target = skills_dst / skill_dir.name
                        if not target.exists():
                            shutil.copytree(skill_dir, target)
                log(f"copied skills to {skills_dst}")


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
    index_ts = BAKED_PI_AUTORESEARCH_EXTENSION / "index.ts"
    if not index_ts.is_file():
        raise CampaignError(f"pi-autoresearch index.ts not found at {index_ts} — image is broken")
    preserve = " ".join(
        f"-e {name}"
        for name in (
            "runs lanes hypotheses reviews baseline runtime state.json "
            "campaign.json adapter.json out-of-scope-suggestions.md"
        ).split()
    )
    pre_marker = "git clean -fd 2>/dev/null"
    post_marker = f"git clean -fd {preserve} 2>/dev/null"

    contents = index_ts.read_text()
    pre_count = contents.count(pre_marker)
    if pre_count > 0:
        if pre_count != 1:
            raise CampaignError(
                f"pi-autoresearch {index_ts.name}: expected exactly 1 `{pre_marker}` "
                f"occurrence, got {pre_count} — patch needs updating"
            )
        _atomic_write(index_ts, contents.replace(pre_marker, post_marker))
        log(f"patched {index_ts.name} to preserve workspace dirs")
    elif post_marker in contents:
        pass
    else:
        raise CampaignError(
            f"pi-autoresearch {index_ts.name}: neither the pre- nor post-patch marker is "
            f"present — upstream shape changed, workspace-preservation patch needs updating"
        )


def _patch_pi_ai_anthropic_baseurl() -> None:
    gateway_base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    if not gateway_base:
        return

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
        raise CampaignError("pi-ai models.generated.js not found in any known location — image is broken")

    contents = models_file.read_text()
    marker = '"https://api.anthropic.com"'
    occurrences = contents.count(marker)
    if occurrences == 0:
        if gateway_base in contents:
            log(f"pi-ai models.generated.js already points at {gateway_base}")
            return
        raise CampaignError(
            "pi-ai models.generated.js: neither the Anthropic baseUrl marker nor our gateway URL "
            "is present — pi-ai's bundle shape changed, baseUrl patch needs updating"
        )

    replacement = json.dumps(gateway_base)
    patched = contents.replace(marker, replacement)
    _atomic_write(models_file, patched)
    log(f"patched pi-ai models.generated.js: rewrote {occurrences} Anthropic baseUrl occurrence(s) to {replacement}")


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
