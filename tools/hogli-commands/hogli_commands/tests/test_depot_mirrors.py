from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from hogli_commands.depot_mirrors import SHA_PIN_HEADER, mirror_violations

TREE = {
    ".depot/workflows/ci-backend.yml": "steps:\n  - uses: ./.depot/actions/setup-uv\n  - uses: './.github/actions/pnpm-install'\n",
    ".github/actions/setup-uv/action.yml": "name: uv\n",
    ".depot/actions/setup-uv/action.yml": "name: uv\n",
    ".github/actions/pnpm-install/action.yml": "name: pnpm\n",
    ".depot/actions/pnpm-install/action.yml": "name: pnpm with a depot delta\n",
    ".github/actions/semgrep-ci/action.yml": "name: not used by depot\n",
}


LOCKED_SHA = "a" * 40


def _pin_mirror(root: Path, mirror_tag: str, mirror_sha: str) -> None:
    (root / ".github/workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github/workflows/actions.lock").write_text(
        f"dependencies:\n    'actions/checkout@v6.0.2':\n        ref: 'v6.0.2'\n        commit: 'sha1-{LOCKED_SHA}'\n"
    )
    (root / ".github/actions/setup-uv/action.yml").write_text("steps:\n  - uses: actions/checkout@v6.0.2\n")
    (root / ".depot/actions/setup-uv/action.yml").write_text(
        f"{SHA_PIN_HEADER.decode()}steps:\n  - uses: actions/checkout@{mirror_sha} # {mirror_tag}\n"
    )


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
                set(), lambda root: _pin_mirror(root, "v6.0.2", LOCKED_SHA), None, id="mirror-pins-locked-commit"
            ),
            pytest.param(
                set(),
                lambda root: _pin_mirror(root, "v6.0.1", LOCKED_SHA),
                ".depot/actions/setup-uv/ differs",
                id="mirror-pins-other-tag",
            ),
            pytest.param(
                set(),
                lambda root: _pin_mirror(root, "v6.0.2", "b" * 40),
                ".depot/actions/setup-uv/ differs",
                id="mirror-pins-unlocked-commit",
            ),
            pytest.param(
                {".depot/actions/pnpm-install/action.yml"},
                lambda root: shutil.rmtree(root / ".depot/actions/pnpm-install"),
                "but .depot/actions/pnpm-install/ does not exist",
                id="used-mirror-deleted",
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
