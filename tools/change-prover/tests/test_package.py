import ast
from pathlib import Path

import pytest

from change_prover.prove import PROVER_FILES

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
CORE = PACKAGE_ROOT / "change_prover" / "core"
SIDE_EFFECT_MODULES = {"os", "subprocess", "socket", "http", "urllib", "shutil", "pathlib", "importlib"}


def imported_modules(source: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(source.read_text(), filename=str(source))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError(f"{source.name} uses a relative import, which this guard does not resolve")
            names.append(node.module or "")
    return names


@pytest.mark.parametrize("source", sorted(CORE.glob("*.py")), ids=lambda path: path.name)
def test_the_core_imports_no_side_effecting_module_and_no_shell_module(source: Path) -> None:
    for name in imported_modules(source):
        assert name.split(".")[0] not in SIDE_EFFECT_MODULES, f"{source.name} imports {name}"
        if name.split(".")[0] == "change_prover":
            assert name.startswith("change_prover.core"), f"{source.name} imports the shell module {name}"


def test_every_file_the_workflows_run_from_is_pinned() -> None:
    package_files = [
        *(PACKAGE_ROOT / "change_prover").rglob("*.py"),
        PACKAGE_ROOT / "pyproject.toml",
        PACKAGE_ROOT / "uv.lock",
    ]
    unpinned = {str(path.relative_to(REPO_ROOT)) for path in package_files} - set(PROVER_FILES)
    missing = [path for path in PROVER_FILES if not (REPO_ROOT / path).is_file()]
    assert not unpinned
    assert not missing
