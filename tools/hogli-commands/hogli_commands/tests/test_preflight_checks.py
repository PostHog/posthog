from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from hogli_commands.preflight_checks import (
    Finding,
    Scope,
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
"""
MANIFEST_WITHOUT_B = MANIFEST.replace("    scenes-app-b--default--dark:\n        hash: v1.bbb\n", "")
MANIFEST_B_REHASHED = MANIFEST.replace("v1.bbb", "v1.ccc")


def _scope(changed: list[str]) -> Scope:
    return Scope(files=changed, changed=changed, merge_base="abc123", committed_only=True)


def _fake_git(blobs: dict[str, bytes], name_status: bytes = b""):
    def run(*args: str, timeout: float = 20.0) -> bytes | None:
        if args[0] == "diff":
            return name_status
        return blobs.get(args[1])

    return run


class TestSnapshotBaselines:
    @pytest.mark.parametrize(
        "after,changed,expected_status",
        [
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/backend/api.py"], "fail"),
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/frontend/B.stories.tsx"], "pass"),
            (MANIFEST_B_REHASHED, ["frontend/snapshots.yml"], "pass"),
        ],
    )
    def test_removal_blocks_only_without_a_story_change(
        self, after: str, changed: list[str], expected_status: str
    ) -> None:
        blobs = {"abc123:frontend/snapshots.yml": MANIFEST.encode(), "HEAD:frontend/snapshots.yml": after.encode()}
        with patch("hogli_commands.preflight_checks._git", side_effect=_fake_git(blobs)):
            status, detail = check_snapshot_baselines(_scope(changed))

        assert status == expected_status
        if expected_status == "fail":
            assert "scenes-app-b--default--dark" in detail


def _findings_from_tree(semgrep: list[str], root: Path) -> dict[Finding, list[int]]:
    found: dict[Finding, list[int]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line:
                found.setdefault(("prefer-frozen-dataclasses", relative, line), []).append(number)
    return found


class TestSemgrepDevex:
    @pytest.mark.parametrize(
        "blobs,name_status,changed,expected_status,expected_fragment",
        [
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"\nold"},
                b"",
                ["posthog/a.py"],
                "pass",
                "no new findings",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nnew"},
                b"",
                ["posthog/a.py"],
                "fail",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nold"},
                b"",
                ["posthog/a.py"],
                "fail",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/moved/a.py": b"old"},
                b"R100\0posthog/a.py\0posthog/moved/a.py\0",
                ["posthog/moved/a.py"],
                "pass",
                "no new findings",
            ),
            (
                {"HEAD:products/desktop/a.py": b"new"},
                b"",
                ["products/desktop/a.py"],
                "skipped",
                "no file to scan",
            ),
        ],
    )
    @patch("hogli_commands.preflight_checks._semgrep_findings", side_effect=_findings_from_tree)
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_only_findings_the_branch_introduced_block(
        self,
        mock_which: MagicMock,
        mock_version: MagicMock,
        mock_findings: MagicMock,
        blobs: dict[str, bytes],
        name_status: bytes,
        changed: list[str],
        expected_status: str,
        expected_fragment: str,
    ) -> None:
        with patch("hogli_commands.preflight_checks._git", side_effect=_fake_git(blobs, name_status)):
            status, detail = check_semgrep_devex(_scope(changed))

        assert status == expected_status
        assert expected_fragment in detail

    @patch("hogli_commands.preflight_checks._semgrep_findings", return_value=None)
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_a_scan_with_no_report_skips_instead_of_blocking(
        self, mock_which: MagicMock, mock_version: MagicMock, mock_findings: MagicMock
    ) -> None:
        blobs = {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nnew"}
        with patch("hogli_commands.preflight_checks._git", side_effect=_fake_git(blobs)):
            status, _ = check_semgrep_devex(_scope(["posthog/a.py"]))

        assert status == "skipped"


WORKFLOW = ".github/workflows/ci-backend.yml"
EVERY_LANE = ["fe:core", "py:core", "rust:core"]


def _node_output(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")


class TestMergeQueueLane:
    @pytest.mark.parametrize(
        "changed,summary,narrowed,expected_status",
        [
            (
                [WORKFLOW, "products/x/backend/api.py"],
                {"is_all": True, "tripwire_files": [WORKFLOW]},
                ["py:core"],
                "warning",
            ),
            ([WORKFLOW, "common/new/x.py"], {"is_all": True, "tripwire_files": [WORKFLOW]}, EVERY_LANE, "pass"),
            ([WORKFLOW], {"is_all": True, "tripwire_files": [WORKFLOW]}, None, "pass"),
            (["products/x/backend/api.py"], {"is_all": False, "target_count": 1, "tripwire_files": []}, None, "pass"),
        ],
    )
    @patch("hogli_commands.preflight_checks._git", return_value=b"")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/node")
    def test_warns_only_when_splitting_the_pr_would_narrow_the_lane(
        self,
        mock_which: MagicMock,
        mock_git: MagicMock,
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
