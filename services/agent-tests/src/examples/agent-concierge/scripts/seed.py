#!/usr/bin/env python3
"""
Idempotent seed for the agent concierge.

Promotes the bundle in this directory's parent into a target PostHog project.
First run creates the application + revision and promotes; subsequent runs
either no-op (bundle sha256 matches live) or branch a new draft, upload the
current bundle, validate, freeze, and promote — leaving the previously-live
revision archived.

Usage:
    PAT=phx_... POSTHOG_API=http://localhost:8010 PROJECT_ID=1 \
        python services/agent-tests/src/examples/agent-concierge/scripts/seed.py

Env vars:
    PAT            PostHog personal API key with agents:write scope
    POSTHOG_API    Base API URL (default http://localhost:8010)
    PROJECT_ID     Target project id (default 1)
    SLUG           Application slug (default agent-concierge)
    DRY_RUN        If '1', print what would happen without mutating
    SPEC_FILE      Override path to spec.json (default sibling spec.json)
    BUNDLE_ROOT    Override bundle directory (default this script's parent)
    MCP_URL        Rewrite every mcps[].url (local-dev override)
    MCP_URL_<id>   Rewrite only the mcps entry whose id matches; wins over MCP_URL

Exit codes:
    0  success (deployed, re-promoted, or no-op)
    1  blocked by validation or platform error
    2  bad env / missing PAT
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BUNDLE_ROOT = Path(os.environ.get("BUNDLE_ROOT", SCRIPT_DIR.parent))
SPEC_FILE = Path(os.environ.get("SPEC_FILE", BUNDLE_ROOT / "spec.json"))
SLUG = os.environ.get("SLUG", "agent-concierge")
PAT = os.environ.get("PAT")
API = os.environ.get("POSTHOG_API", "http://localhost:8010").rstrip("/")
PROJECT_ID = os.environ.get("PROJECT_ID", "1")
DRY_RUN = os.environ.get("DRY_RUN") == "1"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{API}/api/projects/{PROJECT_ID}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {PAT}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            payload = r.read().decode() or "{}"
            return r.status, json.loads(payload)
    except urllib.error.HTTPError as e:
        response_body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(response_body)
        except json.JSONDecodeError:
            return e.code, {"raw": response_body}


def log(msg: str) -> None:
    prefix = "[DRY] " if DRY_RUN else "[seed] "
    print(prefix + msg, flush=True)  # noqa: T201 — CLI script


# ---------------------------------------------------------------------------
# Spec / bundle loading
# ---------------------------------------------------------------------------


def load_v0_spec() -> dict:
    """Load the forward-looking spec.json and strip features the platform
    doesn't accept yet (resume block). Auth is multi-mode natively;
    we pass spec.auth.modes through verbatim. `mcps[]` uses the flat
    `{ id, url, tools[] }` shape — destructive remote tools carry inline
    approval gating via `tools[].approval_policy`.
    """
    spec = json.loads(SPEC_FILE.read_text())

    spec["tools"] = [t for t in spec.get("tools", []) if t.get("kind") in ("native", "custom", "client")]

    # spec.auth is now `{ modes: [...] }` — the platform accepts this
    # directly. AUTH_MODE env overrides the bundle's modes for local
    # testability (use `AUTH_MODE=public` to skip auth, `AUTH_MODE=pat`
    # to require a bearer, etc.). Production should leave the bundle's
    # default modes in place.
    auth_mode_override = os.environ.get("AUTH_MODE")
    if auth_mode_override:
        if auth_mode_override == "shared_secret":
            die("AUTH_MODE=shared_secret requires a header — use the bundle's modes instead")
        spec["auth"] = {"modes": [{"type": auth_mode_override}]}
    elif "modes" not in spec.get("auth", {}):
        # Backstop for older bundles that still use single-mode shape.
        spec["auth"] = {"modes": [{"type": "public"}]}

    spec.pop("resume", None)

    # Triggers — strip config fields the current schema doesn't accept yet.
    # Today: chat allows `require_auth` only; mcp allows nothing.
    allowed_trigger_config = {
        "chat": {"require_auth"},
        "mcp": set(),
        "webhook": {"path", "secret"},
        "slack": {"channel_id", "mention_only", "trusted_workspaces"},
        "cron": {"schedule", "timezone"},
    }
    for t in spec.get("triggers", []):
        cfg = t.setdefault("config", {})
        allowed = allowed_trigger_config.get(t.get("type"), set())
        for k in list(cfg.keys()):
            if k not in allowed:
                cfg.pop(k)
        if t.get("type") == "chat":
            cfg.setdefault("require_auth", False)

    # MCP URL overrides — let a local seed point at localhost:8787/mcp without
    # editing the canonical bundle. Two forms:
    #   MCP_URL=...                → rewrites every mcp's `url`
    #   MCP_URL_<mcp_id>=...       → rewrites only the entry whose id matches
    # Per-id wins over the bare form.
    bare_override = os.environ.get("MCP_URL")
    for m in spec.get("mcps", []):
        per_id = os.environ.get(f"MCP_URL_{m.get('id', '')}")
        override = per_id or bare_override
        if override:
            m["url"] = override

    return spec


def load_bundle_files() -> dict[str, str]:
    files: dict[str, str] = {}
    files["agent.md"] = (BUNDLE_ROOT / "agent.md").read_text()
    skills_dir = BUNDLE_ROOT / "skills"
    if skills_dir.is_dir():
        for f in sorted(skills_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                files[f"skills/{f.name}"] = f.read_text()
    tests_dir = BUNDLE_ROOT / "tests"
    if tests_dir.is_dir():
        for f in sorted(tests_dir.iterdir()):
            if f.is_file() and f.suffix == ".json":
                files[f"tests/{f.name}"] = f.read_text()
    return files


def per_file_sha256(files: dict[str, str]) -> dict[str, str]:
    """Per-file sha256, mirroring what the janitor stores in its manifest.
    Used to diff against the live revision's manifest for idempotency."""
    return {path: hashlib.sha256(content.encode()).hexdigest() for path, content in files.items()}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def find_or_create_application() -> str:
    status, payload = _req("GET", "/agent_applications/")
    if status != 200:
        die(f"failed to list applications: {status} {payload}")
    for app in payload.get("results", []):
        if app.get("slug") == SLUG:
            log(f"application exists: {app['id']}")
            return app["id"]
    log(f"creating application {SLUG}")
    if DRY_RUN:
        return "dry-run-app-id"
    status, payload = _req(
        "POST",
        "/agent_applications/",
        {"name": "Agent concierge", "slug": SLUG, "description": "Meta-agent for the platform.", "archived": False},
    )
    if status not in (200, 201):
        die(f"create failed: {status} {payload}")
    return payload["id"]


def create_draft(app_id: str, parent: str | None, spec: dict) -> str:
    log(f"creating draft (parent={parent or 'none'})")
    if DRY_RUN:
        return "dry-run-rev-id"
    if parent:
        # new_draft branches from the named live revision, copying its bundle.
        # We then overwrite the bundle + patch the spec to match what we want.
        status, payload = _req(
            "POST",
            f"/agent_applications/{app_id}/revisions/new_draft/",
            {"application_id": app_id, "source_revision_id": parent},
        )
        if status not in (200, 201):
            die(f"new_draft failed: {status} {payload}")
        return payload["revision"]["id"]
    status, payload = _req(
        "POST",
        f"/agent_applications/{app_id}/revisions/",
        {"application_id": app_id, "bundle_uri": f"local://{SLUG}/seed", "spec": spec},
    )
    if status not in (200, 201):
        die(f"draft create failed: {status} {payload}")
    return payload["id"]


def push_bundle(app_id: str, rev_id: str, files: dict[str, str]) -> None:
    log(f"pushing {len(files)} bundle files (mode=replace)")
    if DRY_RUN:
        return
    status, payload = _req(
        "PUT",
        f"/agent_applications/{app_id}/revisions/{rev_id}/bundle/",
        {"files": files, "mode": "replace"},
    )
    if status != 200:
        die(f"bundle update failed: {status} {payload}")


def patch_spec(app_id: str, rev_id: str, spec: dict) -> None:
    log("patching spec")
    if DRY_RUN:
        return
    status, payload = _req(
        "PATCH",
        f"/agent_applications/{app_id}/revisions/{rev_id}/",
        {"spec": spec},
    )
    if status not in (200, 202):
        die(f"spec patch failed: {status} {payload}")


def validate(app_id: str, rev_id: str) -> None:
    log("validating")
    if DRY_RUN:
        return
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/validate/")
    if status != 200 or not payload.get("ok", False):
        die(f"validate failed: {status} {json.dumps(payload, indent=2)}")
    log(f"  ok: {len(payload.get('resolved_natives', []))} natives resolved")


def freeze(app_id: str, rev_id: str) -> str:
    log("freezing")
    if DRY_RUN:
        return "dry-run-sha"
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/freeze/")
    if status != 200:
        die(f"freeze failed: {status} {payload}")
    return payload.get("bundle_sha256", "")


def promote(app_id: str, rev_id: str) -> None:
    log(f"promoting {rev_id} → live")
    if DRY_RUN:
        return
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/promote/")
    if status != 200:
        die(f"promote failed: {status} {payload}")


def get_live(app_id: str) -> tuple[str | None, dict[str, str] | None, dict | None]:
    """Returns (live_revision_id, {path: sha256}, spec) or (None, None, None)."""
    status, payload = _req("GET", f"/agent_applications/{app_id}/")
    if status != 200:
        return None, None, None
    rev_id = payload.get("live_revision")
    if not rev_id:
        return None, None, None
    status, rev = _req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/")
    spec = rev.get("spec") if status == 200 else None
    status, manifest = _req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/manifest/")
    if status != 200:
        return rev_id, None, spec
    return rev_id, {f["path"]: f["sha256"] for f in manifest.get("files", [])}, spec


def die(msg: str) -> None:
    print(f"[seed] FATAL: {msg}", file=sys.stderr, flush=True)  # noqa: T201 — CLI script
    sys.exit(1)


def main() -> None:
    if not PAT:
        print("[seed] FATAL: PAT env var required", file=sys.stderr)  # noqa: T201 — CLI script
        sys.exit(2)
    log(f"target: {API} project={PROJECT_ID} slug={SLUG}")
    spec = load_v0_spec()
    files = load_bundle_files()
    target_manifest = per_file_sha256(files)
    log(f"target bundle: {len(files)} files")

    app_id = find_or_create_application()
    live_rev, live_manifest, live_spec = get_live(app_id)
    log(f"current live: rev={live_rev}")

    if live_rev and live_manifest == target_manifest and live_spec == spec:
        log("bundle manifest AND spec match live — no-op")
        return
    if live_rev and live_manifest == target_manifest and live_spec != spec:
        log("bundle matches but spec drifted — re-promoting")
    elif live_rev and live_manifest != target_manifest:
        log("bundle drifted — re-promoting")

    rev_id = create_draft(app_id, parent=live_rev, spec=spec)
    push_bundle(app_id, rev_id, files)
    patch_spec(app_id, rev_id, spec)
    validate(app_id, rev_id)
    new_sha = freeze(app_id, rev_id)
    log(f"frozen sha={new_sha[:12]}...")
    promote(app_id, rev_id)
    log(f"DONE: {SLUG} live at {rev_id}")


if __name__ == "__main__":
    main()
