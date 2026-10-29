"""Tests for the shared pr-assets storage module.

These pin the storage contract both upload commands depend on: one signed commit per
invocation, commit-pinned URLs in input order, the GraphQL failure handling that a
status-code check would miss, the stale-head retry, and the validation gates.
"""

from __future__ import annotations

import re
import base64
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import Mock, patch

import click
from hogli_commands import github_auth, pr_assets

_KEY_RE = r"\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PNG_ONLY = frozenset({"png"})


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake bytes")
    return path


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")


def _resp(payload: dict[str, Any], status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, ok=status < 400, json=lambda: payload)


def _head(oid: str = "head1", branch: str = "main") -> SimpleNamespace:
    return _resp({"data": {"repository": {"defaultBranchRef": {"name": branch, "target": {"oid": oid}}}}})


def _committed(oid: str) -> SimpleNamespace:
    return _resp({"data": {"createCommitOnBranch": {"commit": {"oid": oid}}}})


def _failed(**error: str) -> SimpleNamespace:
    return _resp({"data": {"createCommitOnBranch": None}, "errors": [error]})


def _stale() -> SimpleNamespace:
    return _failed(type="STALE_DATA", message='Expected branch to point to "x" but it did not.')


@contextmanager
def _session(*responses: SimpleNamespace) -> Iterator[Mock]:
    session = Mock()
    session.post.side_effect = list(responses)
    with patch.object(pr_assets.requests, "Session", return_value=session):
        yield session


def _additions(session: Mock) -> list[dict[str, str]]:
    return session.post.call_args.kwargs["json"]["variables"]["input"]["fileChanges"]["additions"]


def _expected_heads(session: Mock) -> list[str]:
    return [
        call.kwargs["json"]["variables"]["input"]["expectedHeadOid"]
        for call in session.post.call_args_list
        if "createCommitOnBranch" in call.kwargs["json"]["query"]
    ]


def test_publishes_every_file_in_one_commit_with_urls_in_input_order(png: Path, tmp_path: Path, token: None) -> None:
    # One commit per invocation is what keeps concurrent uploads from colliding on expectedHeadOid.
    second = tmp_path / "after.png"
    second.write_bytes(b"\x89PNG second")

    with _session(_head(), _committed("c0ffee")) as session:
        urls = pr_assets.publish([png, second], message="add screenshot")

    assert session.post.call_count == 2  # one head read, one mutation
    additions = _additions(session)
    assert len(additions) == 2
    assert [url.split("/c0ffee/")[1] for url in urls] == [addition["path"] for addition in additions]
    assert all(url.startswith("https://raw.githubusercontent.com/PostHog/pr-assets/c0ffee/") for url in urls)


def test_sends_newline_free_base64_under_a_dated_key(png: Path, token: None) -> None:
    with _session(_head(), _committed("c0ffee")) as session:
        pr_assets.publish([png], message="add screenshot")

    addition = _additions(session)[0]
    assert addition["contents"] == base64.b64encode(png.read_bytes()).decode()
    assert "\n" not in addition["contents"]  # GraphQL rejects line-wrapped base64
    assert re.fullmatch(_KEY_RE + r"\.png", addition["path"])


def test_upload_uses_cli_login_instead_of_application_token(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "app-tok")
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: "/usr/bin/gh")
    with (
        patch.object(github_auth.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="user-tok\n")),
        _session(_head(), _committed("c0ffee")) as session,
    ):
        urls = pr_assets.publish([png], message="add screenshot")

    assert "/c0ffee/" in urls[0]
    assert session.post.call_args.kwargs["headers"]["Authorization"] == "Bearer user-tok"


@pytest.mark.parametrize(
    ("error_type", "message"),
    [("FORBIDDEN", "nope"), ("NOT_FOUND", "Branch not found"), ("INTERNAL", "Something went wrong")],
)
def test_operation_failure_is_surfaced_even_though_http_is_200(
    png: Path, token: None, error_type: str, message: str
) -> None:
    with _session(_head(), _failed(type=error_type, message=message)):
        with pytest.raises(click.ClickException, match=f"upload failed: {message}"):
            pr_assets.publish([png], message="add screenshot")


@pytest.mark.parametrize(
    "before_failure",
    [[], [_head(), _stale()]],
    ids=["first_read", "retry_read"],
)
def test_failed_head_read_stays_a_plain_error(png: Path, token: None, before_failure: list[SimpleNamespace]) -> None:
    # A rate limit or a revoked token answers the head read with an errors array. Letting
    # that escape prints a traceback instead of a message telling the caller what to do.
    with _session(*before_failure, _failed(type="RATE_LIMITED", message="API rate limit exceeded")):
        with pytest.raises(click.ClickException, match="could not read PostHog/pr-assets"):
            pr_assets.publish([png], message="add screenshot")


def test_stale_head_is_retried_against_a_freshly_read_head(png: Path, token: None) -> None:
    with _session(_head("head1"), _stale(), _head("head2"), _committed("c0ffee")) as session:
        urls = pr_assets.publish([png], message="add screenshot")

    assert "/c0ffee/" in urls[0]
    assert _expected_heads(session) == ["head1", "head2"]  # reusing head1 would fail forever


def test_gives_up_after_repeated_stale_heads(png: Path, token: None) -> None:
    losing_race = [_head(f"head{attempt}") for attempt in range(pr_assets._MAX_ATTEMPTS)]
    responses = [_head("head0")]
    for head in losing_race:
        responses += [_stale(), head]

    with _session(*responses):
        with pytest.raises(click.ClickException, match="nothing was published"):
            pr_assets.publish([png], message="add screenshot")


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Bad credentials"),
        (403, "API rate limit exceeded"),
        (403, "Resource not accessible by personal access token"),
        (502, "Service unavailable"),
        (502, None),
    ],
)
def test_http_failure_preserves_status_and_github_reason(
    png: Path, token: None, status: int, message: str | None
) -> None:
    response = _resp({"message": message}, status)
    if message is None:
        response.json = Mock(side_effect=ValueError("HTML error page"))
    expected = f"HTTP {status}: {message}" if message else f"HTTP {status}"
    with _session(_head(), response):
        with pytest.raises(click.ClickException, match=expected):
            pr_assets.publish([png], message="add screenshot")


def test_missing_token_names_how_to_supply_one(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: None)  # no env, no gh -> no token

    with pytest.raises(click.ClickException, match="GH_TOKEN"):
        pr_assets.publish([png], message="add screenshot")


def test_validate_rejects_symlink_before_reading_target(tmp_path: Path) -> None:
    # A `screenshot.png` symlink pointing at a sensitive file must be refused before its
    # target is stat'd or read; the .png name would otherwise pass the ext gate and upload .env.
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    with pytest.raises(click.ClickException, match="symlink"):
        pr_assets.validate(link, _PNG_ONLY, 10)


def test_validate_rejects_extension_outside_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"data")
    with pytest.raises(click.ClickException, match="unsupported"):
        pr_assets.validate(path, _PNG_ONLY, 10)


def test_validate_rejects_oversized_file(tmp_path: Path, png: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x00" * (1024 * 1024 + 1))
    with pytest.raises(click.ClickException, match="exceeds the 1 MB limit"):
        pr_assets.validate(big, _PNG_ONLY, 1)
    assert pr_assets.validate(png, _PNG_ONLY, 1) == "png"
