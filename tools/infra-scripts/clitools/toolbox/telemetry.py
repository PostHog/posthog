#!/usr/bin/env python3
"""Best-effort usage telemetry for the toolbox CLI.

Sends a single event per invocation via the PostHog Python SDK (``posthog``, see
https://posthog.com/docs/libraries/python). The SDK is a declared dependency of
this tool (see ``requirements.txt``); if it isn't installed the capture degrades
to a no-op. Every failure is swallowed — telemetry must never delay or break
connecting to a pod. The project API key embedded here is a write-only ingestion
key (the same kind shipped in client SDKs), overridable per-environment via
``TOOLBOX_POSTHOG_API_KEY`` / ``TOOLBOX_POSTHOG_HOST``.
"""

import os
import sys
import platform

# Write-only project API key. Safe to embed; override per-environment with the env var.
DEFAULT_API_KEY = "sTMFPsFhdP1Ssg"
DEFAULT_HOST = "https://us.i.posthog.com"

EVENT_NAME = "toolbox cli used"

# The free-text reason is also submitted as a PostHog API-type survey response so
# it lands in the Surveys UI (response browsing + AI summary). Create an API-type
# survey with one open-text question in PostHog, then set SURVEY_ID (or the env var
# below). For a single-question survey the `$survey_response` shorthand binds to the
# first question, so no per-question id is needed. Left empty, the survey submission
# is skipped and only EVENT_NAME fires.
# https://posthog.com/docs/surveys/implementing-custom-surveys
SURVEY_ID = "019ecbd7-19cd-0000-0adf-226a0612404f"
SURVEY_QUESTION_TEXT = "What are you using the toolbox for today?"


def prompt_for_reason() -> str:
    """Ask the user what they're using the toolbox for.

    Skipped when stdin isn't a TTY (CI, piped input, --auto-delete automation) so
    it never blocks a non-interactive run. Returns "" when skipped or on EOF/Ctrl-C.
    """
    if not sys.stdin.isatty():
        return ""
    try:
        return input(f"📝 {SURVEY_QUESTION_TEXT} (press Enter to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        # Don't let an empty/aborted answer derail the run; a Ctrl-C here just skips the question.
        return ""


def _capture_survey_response(client, distinct_id: str, answer: str) -> None:
    """Submit the free-text reason as a PostHog API-type survey response.

    No-op unless the survey id is configured and the user gave an answer, so an
    unconfigured survey or a skipped prompt never emits a half-formed event.
    """
    survey_id = os.environ.get("TOOLBOX_SURVEY_ID", SURVEY_ID)
    if not (survey_id and answer.strip()):
        return

    client.capture(
        event="survey sent",
        distinct_id=distinct_id,
        properties={
            "$survey_id": survey_id,
            # Single-question survey: `$survey_response` binds to the first question.
            "$survey_response": answer,
            "$survey_questions": [{"question": SURVEY_QUESTION_TEXT}],
        },
    )
    print(f"📊 Telemetry: submitted survey response to survey {survey_id}")  # noqa: T201


def capture_invocation(distinct_id: str, properties: dict) -> None:
    """Fire a single best-effort capture event via the PostHog SDK. Never raises."""
    api_key = os.environ.get("TOOLBOX_POSTHOG_API_KEY", DEFAULT_API_KEY)
    host = os.environ.get("TOOLBOX_POSTHOG_HOST", DEFAULT_HOST)
    if not api_key or api_key == "phc_REPLACE_ME":
        # No real key configured — stay silent rather than spamming a dead endpoint.
        print("📊 Telemetry skipped: no PostHog API key configured.")  # noqa: T201
        return

    try:
        # Imported lazily so a missing SDK degrades to a no-op instead of breaking
        # the import of this module. Install with `pip install -r requirements.txt`.
        from posthog import (
            Posthog,  # type: ignore[import-not-found]  # noqa: PLC0415 — optional dep, kept off the import path
        )

        resolved_distinct_id = distinct_id or "unknown"
        client = Posthog(project_api_key=api_key, host=host)
        client.capture(
            event=EVENT_NAME,
            distinct_id=resolved_distinct_id,
            properties={
                **properties,
                "os": platform.system(),
                "os_release": platform.release(),
                "python_version": platform.python_version(),
            },
        )
        print(f"📊 Telemetry: sent '{EVENT_NAME}' event to {host}")  # noqa: T201

        _capture_survey_response(client, resolved_distinct_id, properties.get("usage_reason", ""))

        # Synchronous flush so events aren't lost when the long-lived shell session ends.
        client.shutdown()
    except ImportError:
        print("📊 Telemetry skipped: posthog SDK not installed (pip install -r requirements.txt).")  # noqa: T201
    except Exception as telemetry_error:
        # Best-effort only; never let a send failure block connecting to a pod.
        print(f"📊 Telemetry failed (ignored): {telemetry_error}")  # noqa: T201
