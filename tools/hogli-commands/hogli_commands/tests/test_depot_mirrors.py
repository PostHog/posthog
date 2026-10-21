from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from hogli_commands.depot_mirrors import mirror_violations

TREE = {
    ".depot/workflows/ci-backend.yml": "steps:\n  - uses: ./.depot/actions/setup-uv\n  - uses: './.github/actions/pnpm-install'\n",
    ".github/actions/setup-uv/action.yml": "name: uv\n",
    ".depot/actions/setup-uv/action.yml": "name: uv\n",
    ".github/actions/pnpm-install/action.yml": "name: pnpm\n",
    ".depot/actions/pnpm-install/action.yml": "name: pnpm with a depot delta\n",
    ".github/actions/semgrep-ci/action.yml": "name: not used by depot\n",
}


class TestMirrorViolations:
    @pytest.mark.parametrize(
        "changed,mutate,expected",
        [
            pytest.param(
                {
                    ".github/actions/setup-uv/action.yml",
                    ".depot/actions/setup-uv/action.yml",
                    ".github/actions/pnpm-install/action.yml",
                    ".depot/actions/pnpm-install/action.yml",
                },
                None,
                None,
                id="in-sync-with-delta-mirror",
            ),
            pytest.param({".github/actions/semgrep-ci/action.yml"}, None, None, id="action-depot-does-not-use"),
            pytest.param(
                {".github/actions/setup-uv/action.yml"},
                None,
                "without a matching update to .depot/actions/setup-uv/action.yml",
                id="canonical-action-only",
            ),
            pytest.param(
                {".github/actions/pnpm-install/action.yml"},
                None,
                "without a matching update to .depot/actions/pnpm-install/action.yml",
                id="canonical-delta-action-only",
            ),
            pytest.param(
                set(),
                lambda root: (root / ".depot/actions/setup-uv/action.yml").write_text("drift\n"),
                ".depot/actions/setup-uv/ differs",
                id="exact-mirror-differs",
            ),
            pytest.param(
                {".depot/actions/pnpm-install/action.yml"},
                lambda root: shutil.rmtree(root / ".depot/actions/pnpm-install"),
                "but .depot/actions/pnpm-install/ does not exist",
                id="used-mirror-deleted",
            ),
            pytest.param(
                {".github/workflows/ci-backend.yml"},
                None,
                "without a matching update to .depot/workflows/ci-backend.yml",
                id="canonical-workflow-only",
            ),
        ],
    )
    def test_reports_drift(
        self,
        tmp_path: Path,
        changed: set[str],
        mutate: Callable[[Path], object] | None,
        expected: str | None,
    ) -> None:
        for relative, content in TREE.items():
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(content)
        if mutate:
            mutate(tmp_path)

        violations = mirror_violations(tmp_path, changed)

        if expected is None:
            assert violations == []
        else:
            assert any(expected in violation for violation in violations), violations
