"""Tests for hogli devex:feedback.

The framework's parametrized ``--help`` test already covers command wellformedness;
these guard the one thing it can't see — that a feedback submission still lands as a
well-formed ``hogli_feedback`` event, so the feature can't silently stop reaching the
devex project on a refactor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import patch

from hogli_commands import feedback


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep get_anonymous_id() off the real ~/.config and pin a deterministic key.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "phc_test")
    monkeypatch.delenv("POSTHOG_TELEMETRY_HOST", raising=False)


def test_send_posts_wellformed_feedback_event(isolated_config: None) -> None:
    with patch.object(feedback.requests, "post") as post:
        post.return_value.raise_for_status.return_value = None
        ok, err = feedback._send("reset was slow", "bug", {"environment": "local", "is_agent": True})

    assert ok and err == ""
    url = post.call_args.args[0]
    body = post.call_args.kwargs["json"]
    assert url.endswith("/batch/")
    assert body["api_key"] == "phc_test"

    (event,) = body["batch"]
    assert event["event"] == "hogli_feedback"
    assert event["distinct_id"]
    props = event["properties"]
    assert props["message"] == "reset was slow"
    assert props["category"] == "bug"
    assert props["environment"] == "local" and props["is_agent"] is True
    # Feedback is anonymous — it must not create a person profile.
    assert props["$process_person_profile"] is False


def test_send_without_api_key_never_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTHOG_TELEMETRY_API_KEY", raising=False)
    monkeypatch.setattr(feedback, "_endpoint", lambda: ("https://us.i.posthog.com", ""))
    with patch.object(feedback.requests, "post") as post:
        ok, err = feedback._send("hi", None, {})
    assert ok is False
    assert "no telemetry API key" in err
    post.assert_not_called()


@pytest.mark.parametrize(
    ("env_host", "manifest_host", "expected"),
    [
        ("http://env.example", "http://manifest.example", "http://env.example"),
        (None, "http://manifest.example", "http://manifest.example"),
    ],
    ids=["env_override_wins", "manifest_fallback"],
)
def test_endpoint_host_precedence(
    monkeypatch: pytest.MonkeyPatch, env_host: str | None, manifest_host: str, expected: str
) -> None:
    if env_host is None:
        monkeypatch.delenv("POSTHOG_TELEMETRY_HOST", raising=False)
    else:
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", env_host)
    monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "phc_test")
    with patch.object(feedback, "get_manifest") as gm:
        gm.return_value.config = {"telemetry": {"host": manifest_host, "api_key": "phc_manifest"}}
        host, _ = feedback._endpoint()
    assert host == expected
