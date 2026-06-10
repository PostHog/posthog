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
import argparse

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
        ssh_key=args.ssh_key,
        box_id=getattr(args, "box_id", None),
        cli=args.cli,
        name=args.name,
    )


def build_stack(backend: HoglandBackend, args: argparse.Namespace) -> PostHogPreviewStack:
    return PostHogPreviewStack(
        backend,
        branch=getattr(args, "branch", None),
        image=args.image,
        seed_demo_data=not getattr(args, "no_seed", False),
        reset_db=getattr(args, "reset_db", False),
    )


def cmd_up(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    stack = build_stack(backend, args)
    url = stack.bring_up()
    print(f"box_id={backend.box_id}")
    print(f"url={url}")
    if args.destroy:
        backend.destroy()
        print(f"destroyed {backend.box_id}")
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
    print(f"healthy: {backend.web_url}")
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    backend = build_backend(args)
    backend.destroy()
    print(f"destroyed {args.box_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hogbox_preview", description=__doc__)
    p.add_argument("--backend", default="hogland", help="preview layer (default: hogland)")
    p.add_argument("--host", default=DEFAULT_HOST, help="hogland API host")
    p.add_argument("--snapshot", default="alias:devbox-golden", help="golden snapshot id/alias")
    p.add_argument("--web-port", type=int, default=8000, help="in-guest port PostHog serves on")
    p.add_argument("--image", default=PostHogPreviewStack.IMAGE, help="published posthog image")
    p.add_argument("--ssh-key", default=None, help="ssh private key for the box (default: ssh default)")
    p.add_argument("--cli", default="hogland", help="hogland CLI binary/path")
    p.add_argument(
        "--name", default="posthog-preview", help="box name (must be unique among live boxes; e.g. preview-pr-123)"
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
    up.set_defaults(func=cmd_up)

    cr = sub.add_parser("create", help="provision the box only")
    cr.set_defaults(func=cmd_create)

    mg = sub.add_parser("migrate", help="run postgres + clickhouse migrations on an existing box")
    mg.add_argument("--box-id", required=True)
    mg.set_defaults(func=cmd_migrate)

    sd = sub.add_parser("seed", help="run demo-data seeding on an existing box")
    sd.add_argument("--box-id", required=True)
    sd.set_defaults(func=cmd_seed, no_seed=False)

    he = sub.add_parser("health", help="wait for /_health on an existing box")
    he.add_argument("--box-id", required=True)
    he.add_argument("--timeout", type=int, default=600)
    he.set_defaults(func=cmd_health)

    de = sub.add_parser("destroy", help="tear a box down")
    de.add_argument("--box-id", required=True)
    de.set_defaults(func=cmd_destroy)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
