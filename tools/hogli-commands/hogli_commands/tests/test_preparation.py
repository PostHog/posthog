from __future__ import annotations

import os
from pathlib import Path

import pytest

from click.testing import CliRunner
from hogli.cli import cli


def test_preparation_repairs_missing_workspace_outputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_bin = tmp_path / "bin"
    tool_bin.mkdir()
    sandbox = tool_bin / "dev-sandbox"
    sandbox.write_text('#!/bin/sh\nexec /bin/sh -c "$1"\n')
    sandbox.chmod(0o755)
    for name in ("uv", "pnpm", "turbo"):
        tool = tool_bin / name
        tool.write_text(
            "#!/bin/sh\n"
            'case "$0" in\n'
            '*/uv) mkdir -p "$UV_PROJECT_ENVIRONMENT"; touch "$UV_PROJECT_ENVIRONMENT/ready";;\n'
            "*/pnpm) mkdir -p node_modules; touch node_modules/ready;;\n"
            '*/turbo) test -f node_modules/ready && test -f "$UV_PROJECT_ENVIRONMENT/ready" || exit 1; '
            "mkdir -p workspace/dist; echo ready > workspace/dist/output;;\n"
            "esac\n"
        )
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / ".venv"))
    monkeypatch.setattr("hogli.command_types.REPO_ROOT", tmp_path)
    with monkeypatch.context() as context:
        context.chdir(tmp_path)
        for _ in range(2):
            result = CliRunner().invoke(cli, ["worktree:prepare"])
            assert result.exit_code == 0, result.output
            assert (tmp_path / "workspace/dist/output").read_text() == "ready\n"
            (tmp_path / "workspace/dist/output").unlink()


@pytest.mark.parametrize(
    "dependency", ["node_modules", "frontend/node_modules", "frontend", ".flox", ".flox/cache", ".flox/cache/venv"]
)
def test_preparation_refuses_dependency_directories_linked_to_another_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dependency: str, capfd: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "another-checkout"
    target.mkdir()
    repository = tmp_path / "worktree"
    repository.mkdir()
    link = repository / dependency
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr("hogli.command_types.REPO_ROOT", repository)
    result = CliRunner().invoke(cli, ["worktree:prepare"])
    assert result.exit_code != 0
    assert "must be local directories" in result.output + capfd.readouterr().err
    assert list(target.iterdir()) == []
