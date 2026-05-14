"""Django AppConfig for the live_debugger product.

The `ready()` hook spawns a `HogTraceManager` that polls this same PostHog
instance for the active program list and installs probes in-process. The
manager is per-Granian-worker — each worker runs its own poller and its
own probe bytecode mutations.

Skipped during pytest collection (the poller thread plus the probe wrappers
would interact unpredictably with isolated test runs) and when no project
key is configured.
"""

from __future__ import annotations

import os
import sys
import logging
import threading

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Module-level latch so ready() only ever spawns one manager per process.
# AppConfig.ready() can fire more than once under some Django startup paths
# (e.g. autoreload, certain test runners).
_init_lock = threading.Lock()
_manager_started = False


class LiveDebuggerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.live_debugger.backend"
    label = "live_debugger"

    def ready(self) -> None:
        global _manager_started
        with _init_lock:
            if _manager_started:
                return
            # Tests fire ready() during Django setup. Skip — the manager would
            # spawn a long-lived poller thread that survives the test process.
            if "pytest" in sys.modules:
                return
            _start_manager()
            _manager_started = True


# Hardcoded local-dev defaults. This branch is a hackathon throwaway — values
# are baked in to avoid env-var plumbing through phrocs. Both are the standard
# `bin/start` / hogli dev fixtures: the local-team project key and the local
# dev personal API key. Override via env if your local setup is different.
_DEFAULT_PROJECT_KEY = "phc_Cd5QqajYtHQrwIlIjlEXPPdDxJEuY8sNUfIXnzGEBzn"
_DEFAULT_PERSONAL_KEY = "phx_dev_local_test_api_key_1234567890abcdef"
_DEFAULT_HOST = "http://localhost:8010"


def _start_manager() -> None:
    """Build a PostHog client and hand it to `HogTraceManager.start()`.

    Reads `POSTHOG_LIVE_DEBUGGER_{PROJECT_KEY,PERSONAL_KEY,HOST}` from env,
    falling back to local-dev fixtures so the manager works out-of-the-box
    against a `hogli start` PostHog without any extra setup.
    """
    project_key = os.environ.get("POSTHOG_LIVE_DEBUGGER_PROJECT_KEY", _DEFAULT_PROJECT_KEY)
    personal_key = os.environ.get("POSTHOG_LIVE_DEBUGGER_PERSONAL_KEY", _DEFAULT_PERSONAL_KEY)
    host = os.environ.get("POSTHOG_LIVE_DEBUGGER_HOST", _DEFAULT_HOST)

    try:
        from libdebugger.manager import HogTraceManager
        from posthoganalytics import Posthog

        client = Posthog(
            project_api_key=project_key,
            host=host,
            personal_api_key=personal_key,
        )
        manager = HogTraceManager(client, poll_interval=30)
        manager.start()
        logger.info("Live debugger manager started (host=%s, poll_interval=30s)", host)
    except Exception:
        logger.exception("Failed to start live debugger manager; continuing without it")
