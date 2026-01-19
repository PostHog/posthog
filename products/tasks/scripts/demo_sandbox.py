#!/usr/bin/env python3
"""
Demo: Modal Sandbox with snapshot restore + Claude Code

Run: flox activate -- bash -c "python products/tasks/scripts/demo_sandbox.py"
"""

# ruff: noqa: T201, E402
import os
import sys
import time
import logging
import warnings
import threading
from pathlib import Path

# Suppress all the noisy logs
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["STRUCTLOG_SILENCE"] = "1"
os.environ["LOG_LEVEL"] = "CRITICAL"

from dotenv import load_dotenv

root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(root))
load_dotenv(root / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()


from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.modal_sandbox import ModalSandbox
from products.tasks.backend.services.sandbox import SandboxConfig

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def main():
    section("Create & Setup Sandbox")

    with status("Creating sandbox") as t:
        sandbox = ModalSandbox.create(
            SandboxConfig(
                name="demo",
                memory_gb=8,
                cpu_cores=4,
                environment_variables={"ANTHROPIC_API_KEY": API_KEY},
            )
        )

    done(f"Sandbox ready ({sandbox.id})", t.elapsed)

    with status("Cloning posthog-js") as t:
        sandbox.execute("git clone --depth 1 https://github.com/PostHog/posthog-js.git /workspace/posthog-js")

    done("Cloned posthog-js", t.elapsed)

    with status("Installing Claude Code") as t:
        sandbox.execute("npm install -g @anthropic-ai/claude-code")

    done("Claude Code installed", t.elapsed)

    section("Snapshot")

    with status("Snapshotting sandbox") as t:
        snapshot = save_snapshot(sandbox.create_snapshot())

    done("Snapshot saved", t.elapsed)

    sandbox.destroy()

    section("Restore from Snapshot")

    with status("Restoring snapshot") as t:
        restored = ModalSandbox.create(
            SandboxConfig(
                name="restored",
                snapshot_id=str(snapshot.id),
                memory_gb=8,
                cpu_cores=4,
                environment_variables={"ANTHROPIC_API_KEY": API_KEY},
            )
        )

    done("Snapshot restored (repo + Claude Code pre-installed!)", t.elapsed)

    section("Execute Unsafe Code (safely!)")

    result = restored.execute("""
        echo "🔒 Running as: $(whoami)"
        echo "📁 I can read /etc/passwd:"
        head -3 /etc/passwd
        echo ""
        echo "💀 I could run: rm -rf / --no-preserve-root"
        echo "   ...but I won't. Point is: this sandbox is isolated!"
    """)

    print(result.stdout)

    section("Cleanup")

    restored.destroy()
    snapshot.delete()
    done("Done")


# ─────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────

CYAN = "\033[96m"
GREEN = "\033[92m"
DIM = "\033[2m"
BOLD = "\033[1m"
END = "\033[0m"
CLEAR_LINE = "\033[2K\r"


class status:
    """Context manager that shows a spinner while work is happening."""

    def __init__(self, message: str):
        self.message = message
        self.elapsed = 0.0
        self._stop = False
        self._thread = None

    def __enter__(self):
        self._stop = False
        self._start = time.time()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop = True
        self.elapsed = time.time() - self._start
        if self._thread:
            self._thread.join()
        print(CLEAR_LINE, end="")

    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not self._stop:
            elapsed = time.time() - self._start
            print(f"{CLEAR_LINE}{CYAN}{frames[i]}{END} {self.message} {DIM}({elapsed:.1f}s){END}", end="", flush=True)
            i = (i + 1) % len(frames)
            time.sleep(0.08)


def section(title: str):
    print(f"\n{BOLD}{title}{END}\n")


def done(message: str, elapsed: float | None = None):
    if elapsed is not None:
        print(f"{GREEN}✓{END} {message} {DIM}({elapsed:.1f}s){END}")
    else:
        print(f"{GREEN}✓{END} {message}")


def save_snapshot(external_id: str) -> SandboxSnapshot:
    return SandboxSnapshot.objects.create(
        external_id=external_id,
        repos=[],
        status=SandboxSnapshot.Status.COMPLETE,
    )


if __name__ == "__main__":
    main()
