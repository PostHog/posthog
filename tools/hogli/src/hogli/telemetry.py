"""Anonymous opt-out telemetry for hogli CLI.

Events are queued in-process and sent as batch POSTs to a PostHog-compatible
``/batch/`` endpoint -- eagerly via :func:`flush_async`, or blocking via
:func:`flush` (registered atexit, which also joins in-flight sends).

Telemetry is **disabled** unless an API key is configured via the
``telemetry.api_key`` section of ``hogli.yaml`` (or the
``POSTHOG_TELEMETRY_API_KEY`` env var). Standalone users of the hogli
framework never emit events to PostHog's project by default.

Opt-out precedence:
    CI (any common provider) -> POSTHOG_TELEMETRY_OPT_OUT=1 -> DO_NOT_TRACK=1 -> config enabled: false -> no api_key

Config file: ~/.config/posthog/hogli_telemetry.json
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
import atexit
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import click
import requests

from hogli.manifest import get_manifest

_DEFAULT_HOST = "https://us.i.posthog.com"

# Environment variables set by common CI providers. Presence of any one means
# we're in CI: telemetry is disabled, and (where enabled) the `is_ci` event
# property is set from this same list so the gate and the label never diverge.
# Depot CI runners are drop-in GitHub Actions runners and set CI/GITHUB_ACTIONS,
# so they're already covered. Depot sandboxes expose no stable CI marker, and
# DEPOT_TOKEN also lives on developer laptops, so gating on it would wrongly
# suppress real local signal -- deliberately not listed here.
_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "JENKINS_URL", "GITLAB_CI", "CIRCLECI", "BUILDKITE")


def is_ci() -> bool:
    """True when any common CI provider's environment variable is present."""
    return any(os.environ.get(v) for v in _CI_ENV_VARS)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TelemetryConfig(TypedDict, total=False):
    enabled: bool
    anonymous_id: str
    first_run_notice_shown: bool
    is_posthog_org_member: bool
    org_check_timestamp: float


def get_config_path() -> Path:
    return Path.home() / ".config" / "posthog" / "hogli_telemetry.json"


def _load_config() -> TelemetryConfig:
    try:
        return json.loads(get_config_path().read_text())
    except Exception:
        return TelemetryConfig()


def _save_config(config: TelemetryConfig) -> None:
    try:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TelemetryClient
# ---------------------------------------------------------------------------


class TelemetryClient:
    """Queue-based telemetry client that sends events as batch POSTs."""

    def __init__(self) -> None:
        self._queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._inflight: list[threading.Thread] = []

    # -- config-backed helpers --

    @property
    def _telemetry_config(self) -> dict[str, Any]:
        return get_manifest().config.get("telemetry", {}) or {}

    @property
    def _host(self) -> str:
        env_host = os.environ.get("POSTHOG_TELEMETRY_HOST")
        if env_host:
            return env_host
        return self._telemetry_config.get("host", _DEFAULT_HOST)

    @property
    def _api_key(self) -> str:
        env_key = os.environ.get("POSTHOG_TELEMETRY_API_KEY")
        if env_key:
            return env_key
        return self._telemetry_config.get("api_key", "")

    def is_enabled(self) -> bool:
        if is_ci():
            return False
        if os.environ.get("POSTHOG_TELEMETRY_OPT_OUT") == "1":
            return False
        if os.environ.get("DO_NOT_TRACK") == "1":
            return False
        # No API key configured -> no destination to send events to.
        if not self._api_key:
            return False
        return _load_config().get("enabled", True)

    def is_active(self) -> bool:
        """The single emission predicate: a track() call right now would queue and send.

        Stricter than :meth:`is_enabled`: also requires the first-run notice
        flag to have been persisted, which never happens on read-only or
        ephemeral HOMEs. Never raises -- telemetry must not break its host.
        """
        try:
            return self.is_enabled() and bool(_load_config().get("first_run_notice_shown"))
        except Exception as exc:
            _debug(f"is_active check failed (treating as inactive): {exc}")
            return False

    def get_anonymous_id(self) -> str:
        config = _load_config()
        anon_id = config.get("anonymous_id")
        if anon_id:
            return anon_id
        anon_id = str(uuid.uuid4())
        config["anonymous_id"] = anon_id
        _save_config(config)
        return anon_id

    def set_enabled(self, enabled: bool) -> None:
        config = _load_config()
        config["enabled"] = enabled
        _save_config(config)

    def show_first_run_notice_if_needed(self) -> None:
        # CI is auto-opted-out via is_ci(); the notice would be noise in build
        # logs and instructs users to set POSTHOG_TELEMETRY_OPT_OUT=1, which is
        # redundant when the CI gate already disables tracking.
        if is_ci():
            return
        config = _load_config()
        if config.get("first_run_notice_shown"):
            return

        click.echo(
            "\n"
            "hogli collects anonymous usage data to help improve the developer experience.\n"
            "No personal information is collected -- only command names, timing, and\n"
            "environment context (OS, tool versions, dev-environment type).\n"
            "\n"
            "You can opt out at any time:\n"
            "  hogli telemetry:off          (persistent)\n"
            "  POSTHOG_TELEMETRY_OPT_OUT=1  (per-session / CI)\n"
            "  DO_NOT_TRACK=1               (cross-tool convention)\n"
            "\n"
            "Run `hogli telemetry:status` for details.\n",
            err=True,
        )

        config["first_run_notice_shown"] = True
        if "anonymous_id" not in config:
            config["anonymous_id"] = str(uuid.uuid4())
        config.setdefault("enabled", True)
        _save_config(config)

    # -- event tracking --

    def track(self, event: str, properties: dict[str, Any] | None = None) -> None:
        """Queue a single event. No-ops unless telemetry is active."""
        if not self.is_active():
            return

        props: dict[str, Any] = {
            "$process_person_profile": False,
        }
        if properties:
            props.update(properties)

        entry = {
            "event": event,
            "distinct_id": self.get_anonymous_id(),
            "properties": props,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        _debug(f"queued: {event}")
        with self._lock:
            self._queue.append(entry)

    def flush(self, timeout: float = 2.0) -> None:
        """Send queued events and wait for in-flight sends, up to *timeout* total.

        Each send thread is joined at most once across flush calls; a thread
        still alive after its window is abandoned to its daemon fate, so a
        hung send can't stall both the post-command flush and the atexit one.
        """
        self._start_send()
        with self._lock:
            pending, self._inflight = self._inflight, []
        deadline = time.monotonic() + timeout
        for thread in pending:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def flush_async(self) -> None:
        """Send queued events in the background without blocking (joined later
        by :meth:`flush`). On a hard kill the POST is already in flight, so
        eagerly-flushed events usually survive where queued ones never do.
        """
        self._start_send()

    def _start_send(self) -> None:
        # Drain, start, and register in one critical section so a concurrent
        # flush() can never swap _inflight between them: appending first would
        # let it join an unstarted thread (RuntimeError), appending after
        # start outside the lock would let the thread escape the join. The
        # send thread never touches _lock, so starting it here can't deadlock.
        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()
            thread = threading.Thread(target=self._send_batch, args=(batch,), daemon=True)
            thread.start()
            self._inflight.append(thread)

    def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        host = self._host
        api_key = self._api_key
        url = f"{host}/batch/"

        body = {"api_key": api_key, "batch": batch}
        _debug(f"POST {url} ({len(batch)} events)", body)

        try:
            resp = requests.post(url, json=body, timeout=5)
            _debug(f"POST {url} -> {resp.status_code}")
        except Exception as exc:
            _debug(f"POST failed: {exc}")


# ---------------------------------------------------------------------------
# Module-level singleton and public API
# ---------------------------------------------------------------------------

_client = TelemetryClient()


def _flush_at_exit() -> None:
    # Never let telemetry teardown print a traceback at process exit (e.g.
    # thread creation failing under resource exhaustion).
    try:
        _client.flush()
    except Exception:
        pass


atexit.register(_flush_at_exit)


def is_enabled() -> bool:
    return _client.is_enabled()


def is_active() -> bool:
    return _client.is_active()


def get_anonymous_id() -> str:
    return _client.get_anonymous_id()


def set_enabled(enabled: bool) -> None:
    _client.set_enabled(enabled)


def show_first_run_notice_if_needed() -> None:
    _client.show_first_run_notice_if_needed()


def track(event: str, properties: dict[str, Any] | None = None) -> None:
    _client.track(event, properties)


def flush(timeout: float = 2.0) -> None:
    _client.flush(timeout)


def flush_async() -> None:
    _client.flush_async()


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------


def _debug(msg: str, payload: dict[str, Any] | None = None) -> None:
    if os.environ.get("HOGLI_DEBUG") != "1":
        return
    sys.stderr.write(f"[telemetry] {msg}\n")
    if payload:
        sys.stderr.write(f"[telemetry] payload: {json.dumps(payload, indent=2)}\n")
