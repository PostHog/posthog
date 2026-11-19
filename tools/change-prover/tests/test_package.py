import re
import ast
from pathlib import Path

import pytest

import yaml
from change_prover.core import issuer

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


def workflow_inputs(workflow: Path) -> set[str]:
    """The workflow itself and every path its jobs check out or run from the default branch."""
    inputs = {str(workflow.relative_to(REPO_ROOT))}
    jobs = yaml.safe_load(workflow.read_text()).get("jobs") or {}
    for job in jobs.values():
        for step in job.get("steps") or []:
            uses, given = step.get("uses", ""), step.get("with") or {}
            if uses.startswith("./"):
                inputs.add(uses.removeprefix("./").rstrip("/") + "/")
            inputs.update(line.strip() for line in given.get("sparse-checkout", "").splitlines() if line.strip())
            if "node-version-file" in given:
                inputs.add(given["node-version-file"])
            for project in re.findall(r"--project (\S+)", step.get("run", "")):
                inputs.add(project.rstrip("/") + "/")
    return inputs


def test_the_issuer_manifest_covers_every_path_the_workflows_run_from() -> None:
    paths = issuer.parse_manifest((REPO_ROOT / issuer.MANIFEST_PATH).read_bytes(), issuer.MANIFEST_PATH)
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    workflows = sorted([*workflow_dir.glob("dependency-proof*.yml"), *workflow_dir.glob("revert-proof*.yml")])
    assert len(workflows) == 4
    needed = set().union(*(workflow_inputs(workflow) for workflow in workflows))
    # A sparse-checkout entry is a directory or a file, so either form of it may cover it.
    uncovered = {
        path
        for path in needed
        if not any(issuer.covers(entry, path) or entry == path.rstrip("/") + "/" for entry in paths)
    }
    missing = [path for path in paths if not (REPO_ROOT / path).exists()]
    wrong_kind = [path for path in paths if (REPO_ROOT / path).is_dir() != issuer.is_directory(path)]
    assert not uncovered
    assert not missing
    assert not wrong_kind
