"""Start the Temporal worker with eval patches applied.

SANDBOX_REPO_MOUNT_MAP=... DEBUG=1 python -m products.signals.eval.self_driving.harness.run_worker
"""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # Critical pipeline settings — set here so the worker never depends on shell sourcing.
    os.environ.setdefault("PERSONHOG_ADDR", "localhost:50052")
    os.environ.setdefault("CLICKHOUSE_DATABASE", "posthog")
    os.environ.setdefault("TASKS_INACTIVITY_TIMEOUT_SECONDS", "420")

    # Self-configure the repo bind mounts for every authored task — shell env plumbing
    # through flox/bash/fish layers is too fragile to trust for a critical setting.
    if not os.environ.get("SANDBOX_REPO_MOUNT_MAP"):
        from pathlib import Path

        tasks_dir = Path(__file__).resolve().parents[1] / "tasks"
        workspace = Path(os.environ.get("SELFDRIVING_EVAL_WORKSPACE", "/tmp/selfdriving-eval-workspace"))
        entries = [
            f"acme/{p.name}:{workspace / 'repos' / p.name}"
            for p in sorted(tasks_dir.iterdir())
            if (p / "task.json").exists()
        ]
        os.environ["SANDBOX_REPO_MOUNT_MAP"] = ",".join(entries)

    import django

    django.setup()

    from products.signals.eval.self_driving.harness.worker_patch import apply

    apply()

    from django.core.management import call_command

    # Same default query tags manage.py sets — without them every sync_execute in the
    # worker trips the DEBUG-only UntaggedQueryError.
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
        call_command("start_temporal_worker", *sys.argv[1:])


if __name__ == "__main__":
    main()
