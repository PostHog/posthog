"""Tests for the deterministic manifest scripts-key scan."""

import pytest

from manifest_risk import diff_touches_risky_keys


@pytest.mark.parametrize(
    "path, changed_line, risky",
    [
        pytest.param("frontend/package.json", '+    "postinstall": "node evil.js",', True, id="postinstall-added"),
        pytest.param("frontend/package.json", '-    "prepare": "husky",', True, id="lifecycle-removed"),
        pytest.param("frontend/package.json", '+    "scripts": {', True, id="scripts-block"),
        pytest.param("frontend/package.json", '+    "version": "1.2.3",', False, id="version-bump-clean"),
        pytest.param("frontend/package.json", '+    "description": "install helper",', False, id="prose-mention-clean"),
        pytest.param("pyproject.toml", "+[project.scripts]", True, id="pyproject-scripts"),
        pytest.param("pyproject.toml", "+[build-system]", True, id="pyproject-build-system"),
        pytest.param("pyproject.toml", "+line-length = 120", False, id="pyproject-tool-config-clean"),
        pytest.param("common/esbuilder/tsconfig.json", '+    "extends": "evil/tsconfig",', True, id="tsconfig-extends"),
        pytest.param("common/esbuilder/tsconfig.json", '+    "strict": true,', False, id="tsconfig-option-clean"),
        pytest.param("setup.py", "+VERSION = '1.0'", True, id="setup-py-any-change"),
        pytest.param("go.mod", "+replace example.com/x => ../local", True, id="go-mod-replace"),
        pytest.param("go.mod", "+require example.com/x v1.2.3", False, id="go-mod-require-clean"),
        pytest.param("rust/Cargo.toml", '+build = "build.rs"', True, id="cargo-build-script"),
        pytest.param("posthog/api/insight.py", "+import os", False, id="non-manifest-never-risky"),
    ],
)
def test_diff_touches_risky_keys(path: str, changed_line: str, risky: bool) -> None:
    # The deny-list can't see diff content, so this scan is the only
    # deterministic control on manifest scripts edits - if it under-matches,
    # a postinstall hook rides to the LLM-only path; if it over-matches,
    # every version bump hard-denies and the tier-3 calibration is undone.
    diff = f"--- a/{path}\n+++ b/{path}\n@@ -1,3 +1,3 @@\n context line\n{changed_line}\n"
    assert diff_touches_risky_keys(path, diff) is risky


def test_context_lines_do_not_trigger() -> None:
    diff = '--- a/frontend/package.json\n+++ b/frontend/package.json\n@@\n     "scripts": {\n+    "version": "2.0",\n'
    assert diff_touches_risky_keys("frontend/package.json", diff) is False
