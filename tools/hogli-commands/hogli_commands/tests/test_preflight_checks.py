from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

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
        "after,changed,expected_status,removed",
        [
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/backend/api.py"], "advisory", "scenes-app-b"),
            (MANIFEST_WITHOUT_C, ["frontend/snapshots.yml"], "advisory", "scenes-app-c"),
            (MANIFEST_WITHOUT_B, ["frontend/snapshots.yml", "products/x/frontend/B.stories.tsx"], "pass", None),
            (MANIFEST_B_REHASHED, ["frontend/snapshots.yml"], "pass", None),
        ],
    )
    def test_removal_is_flagged_only_without_a_story_change(
        self, after: str, changed: list[str], expected_status: str, removed: str | None
    ) -> None:
        blobs = {"abc123:frontend/snapshots.yml": MANIFEST.encode(), "HEAD:frontend/snapshots.yml": after.encode()}
        with patch("hogli_commands.preflight_checks._git", side_effect=_git_show(blobs)):
            status, detail = check_snapshot_baselines(_scope(changed))

        assert status == expected_status
        if removed:
            assert removed in detail


def _every_line_is_a_finding(semgrep: list[str], contents: dict[str, bytes]) -> dict[Finding, list[int]]:
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
                "fail",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/a.py": b"old\nold"},
                {},
                ["posthog/a.py"],
                "fail",
                "posthog/a.py:2",
            ),
            (
                {"abc123:posthog/a.py": b"old", "HEAD:posthog/moved/a.py": b"old"},
                {"posthog/moved/a.py": "posthog/a.py"},
                ["posthog/moved/a.py"],
                "pass",
                "no new findings",
            ),
            ({"HEAD:posthog/new.py": b"new"}, {}, ["posthog/new.py"], "fail", "posthog/new.py:1"),
            ({"HEAD:frontend/a.png": b"\x89PNG\0\0"}, {}, ["frontend/a.png"], "skipped", "no file to scan"),
        ],
    )
    @patch("hogli_commands.preflight_checks._semgrep_findings", side_effect=_every_line_is_a_finding)
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_only_findings_the_branch_introduced_block(
        self,
        mock_which: MagicMock,
        mock_version: MagicMock,
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

    @patch("hogli_commands.preflight_checks._semgrep_findings", return_value=None)
    @patch("hogli_commands.preflight_checks._semgrep_version", return_value="1.0.0")
    @patch("hogli_commands.preflight_checks.shutil.which", return_value="/usr/bin/uvx")
    def test_an_incomplete_scan_skips_instead_of_blocking(
        self, mock_which: MagicMock, mock_version: MagicMock, mock_findings: MagicMock
    ) -> None:
        with patch("hogli_commands.preflight_checks._git", side_effect=_git_show({"HEAD:posthog/a.py": b"new"})):
            status, _ = check_semgrep_devex(_scope(["posthog/a.py"]))

        assert status == "skipped"


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
