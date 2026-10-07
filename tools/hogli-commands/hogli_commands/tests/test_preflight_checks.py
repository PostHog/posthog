from __future__ import annotations

import re
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from hogli.telemetry import _CI_ENV_VARS
from hogli_commands.preflight_checks import (
    Finding,
    Scope,
    SemgrepUnavailable,
    check_merge_queue_lane,
    check_semgrep_devex,
    check_snapshot_baselines,
)

MANIFEST = """version: 1
config:
    api: https://example.com
snapshots:
    scenes-app-a--default--dark:
        hash: v1.aaa
    scenes-app-b--default--dark:
        hash: v1.bbb
    ? scenes-app-c--default--dark
    :   hash: v1.ccc
"""
MANIFEST_WITHOUT_B = MANIFEST.replace("    scenes-app-b--default--dark:\n        hash: v1.bbb\n", "")
MANIFEST_WITHOUT_C = MANIFEST.replace("    ? scenes-app-c--default--dark\n    :   hash: v1.ccc\n", "")
MANIFEST_B_REHASHED = MANIFEST.replace("v1.bbb", "v1.ddd")


def _scope(changed: list[str]) -> Scope:
    return Scope(files=changed, changed=changed, merge_base="abc123", committed_only=True)


def _git_show(blobs: dict[str, bytes]) -> Callable[..., bytes | None]:
    return lambda _show, ref, timeout=20.0: blobs.get(ref)


class TestSnapshotBaselines:
    @pytest.mark.parametrize(
        "after,stories,expected_status,removed",
        [
            (MANIFEST_WITHOUT_B, {}, "advisory", "scenes-app-b"),
            (MANIFEST_WITHOUT_C, {}, "advisory", "scenes-app-c"),
            (MANIFEST_WITHOUT_B, {"abc123:x/B.stories.tsx": b"    title: 'Scenes-App/B',"}, "pass", None),
            (MANIFEST_WITHOUT_B, {"HEAD:x/A.stories.tsx": b"    title: 'Scenes-App/A',"}, "advisory", "scenes-app-b"),
            (MANIFEST_WITHOUT_B, {"HEAD:x/A.stories.tsx": b"const meta = { title: makeTitle() }"}, "pass", None),
            (MANIFEST_B_REHASHED, {}, "pass", None),
        ],
    )
    @patch("hogli_commands.preflight_checks._renamed_from", return_value={})
    def test_removal_is_flagged_unless_its_own_story_changed(
        self,
        mock_renames: MagicMock,
        after: str,
        stories: dict[str, bytes],
        expected_status: str,
        removed: str | None,
    ) -> None:
        blobs = {
            "abc123:frontend/snapshots.yml": MANIFEST.encode(),
            "HEAD:frontend/snapshots.yml": after.encode(),
            **stories,
        }
        changed = ["frontend/snapshots.yml", *(ref.split(":", 1)[1] for ref in stories)]
        with patch("hogli_commands.preflight_checks._git", side_effect=_git_show(blobs)):
            status, detail = check_snapshot_baselines(_scope(changed))

        assert status == expected_status
        if removed:
            assert removed in detail


def _every_line_is_a_finding(
    contents: dict[str, bytes], command: list[str], *, deadline: float
) -> dict[Finding, list[int]]:
    found: dict[Finding, list[int]] = {}
    for path, content in contents.items():
        for number, line in enumerate(content.decode().splitlines(), start=1):
            if line:
                found.setdefault(("prefer-frozen-dataclasses", path, line), []).append(number)
    return found


class TestSemgrepDevex:
    @pytest.mark.parametrize(
        "blobs,renames,changed,expected_status,expected_fragment",
        [
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"\nold"},
                {},
                ["posthog/a.py"],
                "pass",
                "no new findings",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nnew"},
                {},
                ["posthog/a.py"],
                "advisory",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nold"},
                {},
                ["posthog/a.py"],
                "advisory",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/moved/a.py": b"old"},
                {"posthog/moved/a.py": "posthog/a.py"},
                ["posthog/moved/a.py"],
                "pass",
                "no new findings",
            ),
            ({"HEAD:posthog/new.py": b"new"}, {}, ["posthog/new.py"], "advisory", "posthog/new.py:1"),
            ({"HEAD:frontend/a.png": b"\x89PNG\0\0"}, {}, ["frontend/a.png"], "skipped", "no file to scan"),
        ],
    )
    @patch("hogli_commands.preflight_checks._semgrep_findings", side_effect=_every_line_is_a_finding)
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uv")
    def test_only_findings_the_branch_introduced_are_reported(
        self,
        mock_which: MagicMock,
        mock_findings: MagicMock,
        blobs: dict[str, bytes],
        renames: dict[str, str],
        changed: list[str],
        expected_status: str,
        expected_fragment: str,
    ) -> None:
        with (
            patch("hogli_commands.preflight_checks._git", side_effect=_git_show(blobs)),
            patch("hogli_commands.preflight_checks._renamed_from", return_value=renames),
        ):
            status, detail = check_semgrep_devex(_scope(changed))

        assert status == expected_status
        assert expected_fragment in detail

    @patch(
        "hogli_commands.preflight_checks._semgrep_findings", side_effect=SemgrepUnavailable("tool cache unavailable")
    )
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uv")
    def test_an_incomplete_scan_skips_instead_of_reporting(
        self, mock_which: MagicMock, mock_findings: MagicMock
    ) -> None:
        with patch("hogli_commands.preflight_checks._git", side_effect=_git_show({"HEAD:posthog/a.py": b"new"})):
            status, detail = check_semgrep_devex(_scope(["posthog/a.py"]))

        assert status == "skipped"
        assert "tool cache unavailable" in detail

    @patch("hogli_commands.preflight_checks._semgrep_findings", return_value={})
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uv")
    def test_the_scan_runs_the_semgrep_version_ci_pins(self, mock_which: MagicMock, mock_findings: MagicMock) -> None:
        with patch("hogli_commands.preflight_checks._git", side_effect=_git_show({"HEAD:posthog/a.py": b"new"})):
            status, _ = check_semgrep_devex(_scope(["posthog/a.py"]))

        assert status == "pass"
        command = mock_findings.call_args.args[1]
        assert re.fullmatch(r"semgrep==\d+\.\d+\.\d+", command[command.index("--from") + 1])
        assert "--offline" in command

    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uv")
    def test_baseline_scan_uses_only_the_remaining_check_budget(self, mock_which: MagicMock) -> None:
        clock = [100.0]
        scans = 0
        finding = {
            "check_id": "rule",
            "path": "posthog/a.py",
            "start": {"line": 1},
            "end": {"line": 1},
            "extra": {"severity": "WARNING"},
        }

        def run(
            command: list[str],
            *,
            timeout: float,
            cwd: Path,
            capture_output: bool,
            text: bool,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal scans
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            scans += 1
            duration = 14.0 if scans == 1 else 2.0
            clock[0] += min(duration, timeout)
            if duration > timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"results": [finding]}), stderr="")

        with (
            patch("hogli_commands.preflight_checks.time.monotonic", side_effect=lambda: clock[0]),
            patch("hogli_commands.preflight_checks.subprocess.run", side_effect=run),
            patch(
                "hogli_commands.preflight_checks._git",
                side_effect=_git_show({"HEAD:posthog/a.py": b"old", "abc123:posthog/a.py": b"old"}),
            ),
        ):
            status, detail = check_semgrep_devex(_scope(["posthog/a.py"]))

        assert status == "skipped"
        assert "timed out" in detail
        assert clock[0] == 115.0

    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uv")
    def test_scan_uses_writable_state_when_home_paths_are_unavailable(
        self, mock_which: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / ".github/workflows").mkdir(parents=True)
        (tmp_path / ".github/workflows/ci-security.yaml").write_text(
            "SEMGREP_IMAGE: semgrep/semgrep:1.175.0@sha256:test\n"
        )
        (tmp_path / "posthog").mkdir()
        (tmp_path / "posthog/a.py").write_text("value = 1\n")

        def run(command: list[str], *, env: dict[str, str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            tools = Path(env.get("UV_TOOL_DIR", "/home-paths-forbidden/uv-tools"))
            tools.mkdir(parents=True, exist_ok=True)
            for key in ("SEMGREP_LOG_FILE", "SEMGREP_SETTINGS_FILE"):
                Path(env.get(key, "/home-paths-forbidden/semgrep")).touch()
            return subprocess.CompletedProcess(command, 0, stdout='{"results": []}', stderr="")

        with (
            patch("hogli_commands.preflight_checks.REPO_ROOT", tmp_path),
            patch("hogli_commands.preflight_checks.subprocess.run", side_effect=run),
        ):
            scope = Scope(files=["posthog/a.py"], changed=["posthog/a.py"], merge_base="abc123", committed_only=False)
            status, detail = check_semgrep_devex(scope)

        assert status == "pass"
        assert detail == "no new findings"

    @pytest.mark.parametrize(
        "cached,environment,expected_downloads,expected_fragment",
        [
            (False, {}, 1, "started in the background"),
            (False, {"CI": "true"}, 0, "--prepare-semgrep"),
            (False, {"POSTHOG_TASK_RUN_ID": "run"}, 0, "--prepare-semgrep"),
            (True, {}, 0, "CI will run the check"),
        ],
    )
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/tool")
    def test_a_tool_missing_from_the_cache_downloads_once_in_the_background(
        self,
        mock_which: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cached: bool,
        environment: dict[str, str],
        expected_downloads: int,
        expected_fragment: str,
    ) -> None:
        (tmp_path / ".github/workflows").mkdir(parents=True)
        (tmp_path / ".github/workflows/ci-security.yaml").write_text(
            "SEMGREP_IMAGE: semgrep/semgrep:1.175.0@sha256:test\n"
        )
        (tmp_path / "posthog").mkdir()
        (tmp_path / "posthog/a.py").write_text("value = 1\n")
        for name in (*_CI_ENV_VARS, "POSTHOG_TASK_RUN_ID"):
            monkeypatch.delenv(name, raising=False)
        for name, value in environment.items():
            monkeypatch.setenv(name, value)

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[object]:
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, stdout=b"download-marker\n", stderr=b"")
            if cached and "--version" in command:
                return subprocess.CompletedProcess(command, 0, stdout="1.175.0", stderr="")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error: not found in the cache")

        scope = Scope(files=["posthog/a.py"], changed=["posthog/a.py"], merge_base="abc123", committed_only=False)
        with (
            patch("hogli_commands.preflight_checks.REPO_ROOT", tmp_path),
            patch("hogli_commands.preflight_checks.subprocess.run", side_effect=run),
            patch("hogli_commands.preflight_checks.subprocess.Popen") as mock_popen,
        ):
            status, detail = check_semgrep_devex(scope)
            repeat_status, _ = check_semgrep_devex(scope)

        assert (status, repeat_status) == ("skipped", "skipped")
        assert expected_fragment in detail
        assert mock_popen.call_count == expected_downloads
        if expected_downloads:
            assert mock_popen.call_args.args[0] == ["/usr/bin/tool", "ci:preflight", "--prepare-semgrep"]
            assert mock_popen.call_args.kwargs["start_new_session"] is True


WORKFLOW = ".github/workflows/ci-backend.yml"
PRODUCT_FILE = "products/x/backend/api.py"
EVERY_LANE = ["fe:core", "py:core", "rust:core"]


def _node_output(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")


def _widened(listed: int, total: int) -> dict[str, object]:
    files = [WORKFLOW, *(f".github/workflows/{n}.yml" for n in range(listed - 1))]
    return {"is_all": True, "tripwire_files": files, "tripwire_domains": {"universal": total}}


class TestMergeQueueLane:
    @pytest.mark.parametrize(
        "changed,summary,narrowed,expected_status",
        [
            ([WORKFLOW, PRODUCT_FILE], _widened(1, 1), ["py:core"], "warning"),
            ([WORKFLOW, "common/new/x.py"], _widened(1, 1), EVERY_LANE, "pass"),
            ([WORKFLOW], _widened(1, 1), None, "pass"),
            ([WORKFLOW, PRODUCT_FILE], _widened(20, 25), ["py:core"], "pass"),
            ([PRODUCT_FILE], {"is_all": False, "tripwire_files": []}, None, "pass"),
        ],
    )
    @patch("hogli_commands.preflight_checks._renamed_from", return_value={})
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/node")
    def test_warns_only_when_splitting_the_pr_would_narrow_the_lane(
        self,
        mock_which: MagicMock,
        mock_renames: MagicMock,
        changed: list[str],
        summary: dict[str, object],
        narrowed: list[str] | None,
        expected_status: str,
    ) -> None:
        runs = [_node_output(EVERY_LANE), _node_output(summary), _node_output(narrowed)]
        with patch("hogli_commands.preflight_checks.subprocess.run", side_effect=runs):
            status, detail = check_merge_queue_lane(_scope(changed))

        assert status == expected_status
        if expected_status == "warning":
            assert WORKFLOW in detail
