"""Tests for manifest validation utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from hogli.validate import find_orphan_manifest_entries


def _make_manifest_stub(scripts_dir: Path, data: dict[str, Any]) -> Any:
    """Build a minimal stand-in for the Manifest singleton with the fields we use."""

    class _ManifestStub:
        def __init__(self) -> None:
            self.scripts_dir = scripts_dir
            self.data = data

    return _ManifestStub()


class TestFindOrphanManifestEntries:
    @pytest.mark.parametrize(
        "scripts_present,manifest_data,expected",
        [
            (
                ["real-script"],
                {
                    "tools": {
                        "good": {"bin_script": "real-script"},
                        "bad": {"bin_script": "missing-script"},
                    }
                },
                {"bad"},
            ),
            (
                ["a", "b"],
                {
                    "tools": {
                        "a": {"bin_script": "a"},
                        "b": {"bin_script": "b"},
                    }
                },
                set(),
            ),
            (
                [],
                {
                    "metadata": {"categories": []},
                    "tools": {"only-orphan": {"bin_script": "ghost"}},
                },
                {"only-orphan"},
            ),
            (
                ["real"],
                {
                    "tools": {
                        "noop": {"description": "no bin_script field"},
                        "good": {"bin_script": "real"},
                    }
                },
                set(),
            ),
        ],
        ids=["mixed", "all-present", "all-missing", "skip-entries-without-bin-script"],
    )
    def test_detects_orphans(
        self,
        tmp_path: Path,
        scripts_present: list[str],
        manifest_data: dict[str, Any],
        expected: set[str],
    ) -> None:
        for name in scripts_present:
            (tmp_path / name).write_text("#!/bin/sh\n")

        stub = _make_manifest_stub(tmp_path, manifest_data)
        with patch("hogli.validate.get_manifest", return_value=stub):
            assert find_orphan_manifest_entries() == expected

    def test_returns_empty_when_scripts_dir_missing(self, tmp_path: Path) -> None:
        missing_dir = tmp_path / "does-not-exist"
        stub = _make_manifest_stub(
            missing_dir,
            {"tools": {"a": {"bin_script": "anything"}, "b": {"bin_script": "else"}}},
        )
        with patch("hogli.validate.get_manifest", return_value=stub):
            assert find_orphan_manifest_entries() == set()
