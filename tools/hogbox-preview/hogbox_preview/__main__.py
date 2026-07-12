"""CLI for hogbox previews. Mirrors bin/hobby-ci.py's subcommand shape so it
slots into the same CI flow.

    # one-shot: provision + bring PostHog up, print the URL
    python -m hogbox_preview up --branch "$BRANCH" --host "$HOG_HOST"

    # granular (debug / staged CI), reusing a box:
    python -m hogbox_preview create  --host "$HOG_HOST"
    python -m hogbox_preview seed     --box-id box-xxxx --host "$HOG_HOST"
    python -m hogbox_preview health   --box-id box-xxxx --host "$HOG_HOST"
    python -m hogbox_preview destroy  --box-id box-xxxx --host "$HOG_HOST"

Layer is chosen with --backend (hogland today). The stack is identical across
layers — see stack.py.
"""
# ruff: noqa: T201 — this is a CLI; it prints results for CI to capture.

from __future__ import annotations

import os
import sys
import json
import argparse
import urllib.request

from hogland import APIError, Hogland

from .hogland_backend import HoglandBackend
from .stack import PostHogPreviewStack

DEFAULT_HOST = os.environ.get("HOG_HOST", "https://hogland.hedgehog-kitefin.ts.net")


def build_backend(args: argparse.Namespace) -> HoglandBackend:
    if args.backend != "hogland":
        raise SystemExit(f"backend {args.backend!r} not wired up yet (see digitalocean_backend.py)")
    return HoglandBackend(
        host=args.host,
        snapshot=args.snapshot,
        web_port=args.web_port,
        box_id=getattr(args, "box_id", None),
        name=args.name,
        cpus=args.cpus,
        memory_mib=args.memory_mib,
        disk_gib=args.disk_gib,
        ttl_seconds=args.ttl_seconds,
    )


def build_stack(backend: HoglandBackend, args: argparse.Namespace) -> PostHogPreviewStack:
    return PostHogPreviewStack(
        backend,
        branch=getattr(args, "branch", None),
        image=args.image,
        seed_demo_data=not getattr(args, "no_seed", False),
        reset_db=getattr(args, "reset_db", False),
        frontend_dist_tar=getattr(args, "frontend_dist", None),
    )


def cmd_up(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    stack = build_stack(backend, args)
    url = stack.bring_up()
    print(f"box_id={backend.box_id}")
    # Empty (not the literal "None") when there's no pen, so the CI parser treats
    # it as absent rather than rendering an admin link to /pens/None.
    print(f"pen_id={backend.pen_id or ''}")
    print(f"url={url}")
    if args.destroy:
        backend.destroy()
        print(f"destroyed {backend.box_id}")
    return 0


def cmd_swap_frontend(args: argparse.Namespace) -> int:
    # Deferred frontend swap onto an already-up box (parallel CI flow): `up`
    # brings the box healthy on the :master SPA with no dist, then this lays the
    # PR's freshly-built dist in once the runner finishes building it. Resolves
    # the live box by pen/name — never restores a new one.
    backend = build_backend(args)
    stack = build_stack(backend, args)
    url = stack.swap_frontend_only()
    print(f"box_id={backend.box_id}")
    print(f"url={url}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.provision()
    print(f"box_id={backend.box_id}")
    print(f"url={backend.web_url}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.provision()
    build_stack(backend, args).migrate()
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.provision()  # resolves the existing box when --box-id is set
    build_stack(backend, args).generate_demo_data()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.provision()
    backend.wait_http_ok("/_health", expect=200, timeout=args.timeout)
    # /_health only proves the process is up. Run the authed deep-health probe
    # too so this subcommand catches an unusable app (the personhog-drift 500s
    # slipped past /_health). --no-seed only tolerates a failed demo login
    # (genuinely unseeded box); it no longer skips the probe outright.
    build_stack(backend, args).deep_health()
    print(f"healthy: {backend.web_url}")
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.destroy()
    print(f"destroyed {args.box_id or args.name}")
    return 0


def _pr_state(repo: str, pr: str, token: str) -> str | None:
    """The GitHub state ("open"/"closed") of a PR, or None on any error."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed GitHub host  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return json.load(r).get("state")
    except Exception:  # noqa: BLE001 — a flaky check shouldn't reap a live preview
        return None


def cmd_cleanup_stale(args: argparse.Namespace) -> int:
    """Reap previews whose PR is closed: list the caller's preview-pr-<n> pens,
    check each PR's GitHub state, destroy (box + pen) the closed ones. Backstop
    for a missed PR-close teardown — leaked boxes self-reap at their 24h preview
    TTL, but pens have none, so this clears them. Honours DRY_RUN=true. Needs
    GITHUB_REPOSITORY + GH_TOKEN/GITHUB_TOKEN; without them it can't tell stale
    from live, so it keeps everything."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    if not (repo and token):
        print("cleanup-stale: GITHUB_REPOSITORY + GH_TOKEN required to check PR state; nothing reaped")
        return 0
    client = Hogland(base_url=args.host, timeout=300)
    reaped = 0
    for pen in client.iter_pens():
        name = getattr(pen, "name", "") or ""
        if not name.startswith("preview-pr-"):
            continue
        pr = name[len("preview-pr-") :]
        state = _pr_state(repo, pr, token)
        if state != "closed":
            print(f"{name}: PR #{pr} {state or 'unknown'} -> keep")
            continue
        print(f"{name}: PR #{pr} closed -> {'WOULD destroy' if dry else 'destroying'}")
        if not dry:
            HoglandBackend(host=args.host, name=name).destroy()
            reaped += 1
    print(f"cleanup-stale: reaped {reaped} closed-PR preview(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hogbox_preview", description=__doc__)
    p.add_argument("--backend", default="hogland", help="preview layer (default: hogland)")
    p.add_argument("--host", default=DEFAULT_HOST, help="hogland API host")
    p.add_argument("--snapshot", default="alias:posthog-preview-golden", help="golden snapshot id/alias")
    p.add_argument("--web-port", type=int, default=8000, help="in-guest port PostHog serves on")
    p.add_argument("--image", default=PostHogPreviewStack.IMAGE, help="published posthog image")
    p.add_argument(
        "--name", default="posthog-preview", help="box name (must be unique among live boxes; e.g. preview-pr-123)"
    )
    # Sizing MUST match the golden snapshot being restored ("omit to inherit" is
    # broken server-side). Defaults match the preview golden (snap-753bb8b3eeef,
    # alias posthog-preview-golden) at 8 vCPU / 16 GB / 100 GB.
    p.add_argument("--cpus", type=int, default=8, help="vCPUs (must match the golden's size)")
    p.add_argument("--memory-mib", type=int, default=16384, help="memory MiB (must match the golden's size)")
    p.add_argument("--disk-gib", type=int, default=100, help="rootfs GiB (must match the golden's size)")
    p.add_argument(
        "--ttl-seconds",
        type=int,
        default=1800,
        help="idle TTL in seconds; hogland's reaper hibernates this on_idle=hibernate preview "
        "after it's been idle this long (default 1800 = 30 min). A reviewer's next visit "
        "wakes it in ~30s. Min 60.",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="provision + bring PostHog up (one-shot)")
    up.add_argument("--box-id", default=None, help="reuse an existing box instead of restoring a new one")
    up.add_argument("--branch", default=None, help="posthog branch to check out in the box")
    up.add_argument("--no-seed", action="store_true", help="skip demo-data seeding (generate_demo_data)")
    up.add_argument(
        "--reset-db",
        action="store_true",
        help="wipe pg+clickhouse first, so they migrate fresh & coherent with --image (use when baking a golden)",
    )
    up.add_argument("--destroy", action="store_true", help="tear the box down after (smoke-test mode)")
    up.add_argument(
        "--frontend-dist",
        default=None,
        help="path to a gzipped tar of a prebuilt frontend/dist; serves the PR's own frontend (else the image's :master SPA)",
    )
    up.set_defaults(func=cmd_up)

    sf = sub.add_parser("swap-frontend", help="swap the PR frontend onto an already-up box (deferred, parallel CI)")
    sf.add_argument("--box-id", default=None, help="attach to this box instead of resolving the pen by --name")
    sf.add_argument(
        "--frontend-dist",
        required=True,
        help="path to a gzipped tar of the prebuilt frontend/dist to serve (built on the CI runner)",
    )
    sf.set_defaults(func=cmd_swap_frontend)

    cr = sub.add_parser("create", help="provision the box only")
    cr.set_defaults(func=cmd_create)

    mg = sub.add_parser("migrate", help="run postgres + clickhouse migrations on an existing box")
    mg.add_argument("--box-id", required=True)
    mg.set_defaults(func=cmd_migrate)

    sd = sub.add_parser("seed", help="run demo-data seeding on an existing box")
    sd.add_argument("--box-id", required=True)
    sd.set_defaults(func=cmd_seed, no_seed=False)

    he = sub.add_parser("health", help="wait for /_health, then run the authed deep-health probe")
    he.add_argument("--box-id", required=True)
    he.add_argument("--timeout", type=int, default=600)
    he.add_argument("--no-seed", action="store_true", help="skip the authed deep-health probe (no demo user seeded)")
    he.set_defaults(func=cmd_health)

    de = sub.add_parser("destroy", help="tear a box down")
    de.add_argument(
        "--box-id", default=None, help="box to tear down (falls back to --name lookup, e.g. for CI cleanup)"
    )
    de.set_defaults(func=cmd_destroy)

    sub.add_parser("cleanup-stale", help="reap previews whose PR is closed (cron backstop)").set_defaults(
        func=cmd_cleanup_stale
    )

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except APIError as e:
        # Surface the server's RFC 7807 problem-details body. The SDK exception
        # message alone (e.g. "validation failed") hides which field the server
        # rejected, which makes a CI failure undiagnosable from the log.
        sys.stderr.write(f"[hogbox-preview] hogland API error (HTTP {e.status_code}): {e}\n")
        if getattr(e, "body", None):
            sys.stderr.write(f"[hogbox-preview] details: {json.dumps(e.body, indent=2, default=str)}\n")
        raise


if __name__ == "__main__":
    sys.exit(main())
