from __future__ import annotations

import json
import subprocess

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


def _scope(changed: list[str], files: list[str] | None = None) -> Scope:
    return Scope(files=files or changed, changed=changed, base="origin/master", committed_only=True)


class TestSnapshotBaselines:
    @pytest.mark.parametrize(
        "after,changed,expected_status",
        [
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/backend/api.py"], "fail"),
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/frontend/B.stories.tsx"], "pass"),
            (MANIFEST_B_REHASHED, ["frontend/snapshots.yml"], "pass"),
        ],
    )
    @patch("hogli_commands.preflight_checks._merge_base", return_value="abc123")
    def test_removal_blocks_only_without_a_story_change(
        self, mock_merge_base: MagicMock, after: str, changed: list[str], expected_status: str
    ) -> None:
        shown = {"abc123:frontend/snapshots.yml": MANIFEST.encode(), "HEAD:frontend/snapshots.yml": after.encode()}
        with patch("hogli_commands.preflight_checks._git", side_effect=lambda _show, ref: shown[ref]):
            status, detail = check_snapshot_baselines(_scope(changed))

        assert status == expected_status
        if expected_status == "fail":
            assert "scenes-app-b--default--dark" in detail


GRANDFATHERED: Finding = ("prefer-frozen-dataclasses", "posthog/a.py", "@dataclass\nclass Old:")
INTRODUCED: Finding = ("prefer-frozen-dataclasses", "posthog/a.py", "@dataclass\nclass New:")


class TestSemgrepDevex:
    @pytest.mark.parametrize(
        "before,after,expected_status,expected_fragment",
        [
            ({GRANDFATHERED: [4]}, {GRANDFATHERED: [9]}, "pass", "no new findings"),
            ({GRANDFATHERED: [4]}, {GRANDFATHERED: [4], INTRODUCED: [20]}, "fail", "posthog/a.py:20"),
            ({GRANDFATHERED: [4]}, {GRANDFATHERED: [4, 30]}, "fail", "posthog/a.py:30"),
            ({}, None, "skipped", "no readable report"),
        ],
    )
    @patch("hogli_commands.preflight_checks._git", return_value=b"")
    @patch("hogli_commands.preflight_checks._merge_base", return_value="abc123")
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_only_findings_the_branch_introduced_block(
        self,
        mock_which: MagicMock,
        mock_probe: MagicMock,
        mock_version: MagicMock,
        mock_merge_base: MagicMock,
        mock_git: MagicMock,
        before: dict[Finding, list[int]],
        after: dict[Finding, list[int]] | None,
        expected_status: str,
        expected_fragment: str,
    ) -> None:
        with patch("hogli_commands.preflight_checks._semgrep_findings", side_effect=[before, after]):
            status, detail = check_semgrep_devex(_scope(["tools/hogli-commands/hogli_commands/ci_preflight.py"]))

        assert status == expected_status
        assert expected_fragment in detail

    @patch("hogli_commands.preflight_checks._merge_base", return_value="abc123")
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.subprocess.run", return_value=MagicMock(returncode=2))
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_uninstallable_semgrep_skips_instead_of_blocking(
        self, mock_which: MagicMock, mock_probe: MagicMock, mock_version: MagicMock, mock_merge_base: MagicMock
    ) -> None:
        status, _ = check_semgrep_devex(_scope(["tools/hogli-commands/hogli_commands/ci_preflight.py"]))

        assert status == "skipped"


def _lane_runs(targets: list[str], summary: dict[str, object]) -> list[subprocess.CompletedProcess[str]]:
    return [
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(targets), stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(summary), stderr=""),
    ]


class TestMergeQueueLane:
    @pytest.mark.parametrize(
        "changed,summary,expected_status",
        [
            (
                [".github/workflows/ci-backend.yml", "products/x/backend/api.py"],
                {"is_all": True, "tripwire_files": [".github/workflows/ci-backend.yml"]},
                "warning",
            ),
            (
                [".github/workflows/ci-backend.yml"],
                {"is_all": True, "tripwire_files": [".github/workflows/ci-backend.yml"]},
                "pass",
            ),
            (["products/x/backend/api.py"], {"is_all": False, "target_count": 3, "tripwire_files": []}, "pass"),
        ],
    )
    @patch("hogli_commands.preflight_checks._merge_base", return_value="abc123")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/node")
    def test_warns_only_when_splitting_the_pr_would_narrow_the_lane(
        self,
        mock_which: MagicMock,
        mock_merge_base: MagicMock,
        changed: list[str],
        summary: dict[str, object],
        expected_status: str,
    ) -> None:
        with patch("hogli_commands.preflight_checks.subprocess.run", side_effect=_lane_runs(["py:core"], summary)):
            status, detail = check_merge_queue_lane(_scope(changed))

        assert status == expected_status
        if expected_status == "warning":
            assert ".github/workflows/ci-backend.yml" in detail
