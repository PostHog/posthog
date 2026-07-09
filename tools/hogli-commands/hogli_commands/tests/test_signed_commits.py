from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli_commands.signed_commits import (
    PublishError,
    RawDiffEntry,
    _commit_entries,
    _commit_file_changes,
    _origin_repo,
    git_publish_signed,
    mode_violations,
    parse_raw_diff,
    split_commit_message,
    workflow_paths,
)


def _entry(src_mode: str, dst_mode: str, status: str = "M", path: str = "f.txt") -> RawDiffEntry:
    return RawDiffEntry(src_mode=src_mode, dst_mode=dst_mode, dst_sha="0" * 40, status=status, path=path)


class TestPureHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("feat: one liner", ("feat: one liner", "")),
            ("feat: subject\n\nbody line 1\nbody line 2", ("feat: subject", "body line 1\nbody line 2")),
            ("fix: x\nRefs PROJ-123", ("fix: x", "Refs PROJ-123")),
            ("subject\n\n\n", ("subject", "")),
        ],
        ids=["subject_only", "subject_and_body", "no_blank_line_before_body", "trailing_newlines"],
    )
    def test_split_commit_message(self, raw: str, expected: tuple[str, str]) -> None:
        assert split_commit_message(raw) == expected

    def test_parse_raw_diff(self) -> None:
        z = (
            ":100644 100755 abc def M\0bin/script\0"
            ":000000 120000 000 abc A\0link\0"
            ":100644 000000 abc 000 D\0.github/workflows/ci.yml\0"
        )
        entries = parse_raw_diff(z)
        assert [(e.status, e.path, e.dst_sha) for e in entries] == [
            ("M", "bin/script", "def"),
            ("A", "link", "abc"),
            ("D", ".github/workflows/ci.yml", "000"),
        ]
        assert workflow_paths(entries) == [".github/workflows/ci.yml"]

    @pytest.mark.parametrize(
        ("entry", "violates"),
        [
            (_entry("000000", "120000", "A", "link"), True),
            (_entry("120000", "100644", "T", "link"), True),
            (_entry("000000", "160000", "A", "sub"), True),
            (_entry("100644", "100755"), True),
            (_entry("100755", "100644"), True),
            (_entry("000000", "100755", "A", "bin/new"), True),
            (_entry("100644", "100644"), False),
            (_entry("100755", "100755"), False),
            (_entry("100755", "000000", "D", "bin/old"), False),
        ],
        ids=[
            "symlink_added",
            "symlink_replaced",
            "submodule_added",
            "chmod_plus_x",
            "chmod_minus_x",
            "new_executable",
            "plain_modify",
            "executable_content_edit",
            "executable_deleted",
        ],
    )
    def test_mode_violations(self, entry: RawDiffEntry, violates: bool) -> None:
        assert bool(mode_violations([entry])) is violates


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(repo: Path, branch: str = "master") -> None:
    repo.mkdir(exist_ok=True)
    _run_git(repo, "init", "-q", "-b", branch)
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    _run_git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("one\n")
    _run_git(repo, "add", "a.txt")
    _run_git(repo, "commit", "-q", "-m", "init")


def _add_bare_origin(repo: Path, branch: str, *, set_head: bool) -> None:
    origin = repo.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", branch, str(origin)], check=True, capture_output=True)
    _run_git(repo, "remote", "add", "origin", str(origin))
    _run_git(repo, "push", "-q", "origin", branch)
    if set_head:
        _run_git(repo, "remote", "set-head", "origin", branch)


class TestOriginRepo:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("git@github.com:PostHog/posthog.git", "PostHog/posthog"),
            ("https://github.com/PostHog/posthog", "PostHog/posthog"),
            ("ssh://git@github.com/PostHog/posthog.git", "PostHog/posthog"),
            ("git@corp-github.com:org/repo.git", None),
            ("https://mygithub.com/org/repo", None),
        ],
        ids=["ssh_scp", "https", "ssh_url", "lookalike_scp_host", "lookalike_https_host"],
    )
    def test_host_anchoring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, expected: str | None
    ) -> None:
        _init_repo(tmp_path)
        _run_git(tmp_path, "remote", "add", "origin", url)
        monkeypatch.chdir(tmp_path)
        if expected is None:
            with pytest.raises(PublishError):
                _origin_repo()
        else:
            assert _origin_repo() == expected


class TestBuildFileChanges:
    def test_text_binary_and_deletion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_repo(tmp_path)
        binary = bytes(range(256))
        (tmp_path / "a.txt").unlink()
        (tmp_path / "b.bin").write_bytes(binary)
        (tmp_path / "c.txt").write_text("text\n")
        _run_git(tmp_path, "add", "-A")
        _run_git(tmp_path, "commit", "-q", "-m", "change")
        monkeypatch.chdir(tmp_path)

        changes = _commit_file_changes(_commit_entries("HEAD"))

        assert changes["deletions"] == [{"path": "a.txt"}]
        by_path = {a["path"]: a["contents"] for a in changes["additions"]}
        assert base64.b64decode(by_path["b.bin"]) == binary
        assert base64.b64decode(by_path["c.txt"]) == b"text\n"


class TestGuardRails:
    @pytest.mark.parametrize(
        ("branch", "set_head"),
        [("master", True), ("main", False)],
        ids=["origin_head_set", "main_without_origin_head"],
    )
    def test_refuses_default_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, branch: str, set_head: bool
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, branch=branch)
        _add_bare_origin(repo, branch, set_head=set_head)
        monkeypatch.chdir(repo)
        result = CliRunner().invoke(git_publish_signed, [])
        assert result.exit_code != 0
        assert f"Refusing to publish directly to {branch}" in result.output

    def test_refuses_detached_head(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_repo(tmp_path)
        _run_git(tmp_path, "checkout", "-q", "--detach")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(git_publish_signed, [])
        assert result.exit_code != 0
        assert "Detached HEAD" in result.output

    def test_refuses_merge_in_progress(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_repo(tmp_path)
        _run_git(tmp_path, "checkout", "-q", "-b", "feature")
        (tmp_path / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(git_publish_signed, [])
        assert result.exit_code != 0
        assert "merge is in progress" in result.output

    def test_git_failure_surfaces_stderr_not_traceback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_repo(tmp_path)
        _run_git(tmp_path, "checkout", "-q", "-b", "feature")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(git_publish_signed, [])
        assert result.exit_code != 0
        assert "`git ls-remote --symref origin HEAD` failed:" in result.output
        assert result.exc_info is not None and result.exc_info[0] is SystemExit
