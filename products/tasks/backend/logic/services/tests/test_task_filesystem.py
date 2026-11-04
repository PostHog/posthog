import os
import sys
import json
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.sandbox.images import task_filesystem


@pytest.mark.parametrize("restored", [False, True])
def test_home_seed_enters_the_workspace_only_when_activated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restored: bool
) -> None:
    state = tmp_path / "workspace/.posthog/task-filesystem"
    seed = tmp_path / "image/home"
    seed.mkdir(parents=True)
    (seed / "file").write_text("seed")
    state.mkdir(parents=True)
    home = state / "home"
    if restored:
        home.mkdir()
        (home / "file").write_text("saved")
        (state / "version").write_text(task_filesystem.VERSION)
    monkeypatch.setattr(task_filesystem, "STATE", state)
    monkeypatch.setattr(task_filesystem, "HOME_SEED", seed)
    monkeypatch.setattr(task_filesystem, "RUNTIME", tmp_path / "runtime")

    task_filesystem.prepare_home()

    assert (home / "file").read_text() == ("saved" if restored else "seed")
    assert seed.exists() == restored


def test_pinned_settings_are_recreated_outside_persistent_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    settings = home / ".claude/posthog-session-settings"
    settings.mkdir(parents=True)
    (settings / "old.json").write_text('{"env":{"ANTHROPIC_AUTH_TOKEN":"synthetic-token"}}')
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(task_filesystem, "RUNTIME", runtime)

    task_filesystem.prepare_runtime_home(home)

    assert settings.is_symlink()
    assert not (settings / "old.json").exists()
    (settings / "new.json").write_text("fresh")
    assert (runtime / "claude-session-settings/new.json").read_text() == "fresh"
    assert (runtime / "claude-session-settings").stat().st_mode & 0o777 == 0o700
    task_filesystem.prepare_runtime_home(home)
    assert (settings / "new.json").read_text() == "fresh"


def test_pinned_settings_reject_an_unexpected_symlink(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (home / ".claude/posthog-session-settings").symlink_to(external)
    monkeypatch.setattr(task_filesystem, "RUNTIME", tmp_path / "runtime")

    with pytest.raises(RuntimeError, match="Unexpected runtime path"):
        task_filesystem.prepare_runtime_home(home)
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("linked", ["workspace", "state", "home"])
def test_initialization_rejects_symlinked_state_before_writing(tmp_path: Path, monkeypatch, linked: str) -> None:
    workspace = tmp_path / "workspace"
    state = workspace / ".posthog/task-filesystem"
    runtime = tmp_path / "runtime"
    destination = {"workspace": workspace, "state": state, "home": state / "home"}[linked]
    target = tmp_path / "external"
    target.mkdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(task_filesystem, "WORKSPACE", workspace)
    monkeypatch.setattr(task_filesystem, "STATE", state)
    monkeypatch.setattr(task_filesystem, "RUNTIME", runtime)

    with pytest.raises(RuntimeError, match="real directory"):
        task_filesystem.initialize("vm")

    assert list(target.iterdir()) == []


@pytest.mark.parametrize("saved_version", [None, "1"])
def test_entry_refuses_lost_namespace_instead_of_using_provider_paths(
    tmp_path: Path, saved_version: str | None
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    if saved_version is not None:
        (state / "version").write_text(saved_version)
    output = tmp_path / "executed"
    script = (
        "from pathlib import Path; "
        "from products.tasks.backend.sandbox.images import task_filesystem as fs; "
        f"fs.STATE=Path({str(state)!r}); fs.RUNTIME=Path({str(tmp_path / 'runtime')!r}); "
        f"fs.enter({[sys.executable, '-c', f'from pathlib import Path; Path({str(output)!r}).touch()']!r})"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[6],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert (result.returncode == 0) == (saved_version is None), result.stderr
    assert output.exists() == (saved_version is None)


def test_entry_rejects_reused_namespace_holder_pid(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "ready").write_text(json.dumps({"pid": os.getpid(), "namespace": "mnt:[1]"}))
    monkeypatch.setattr(task_filesystem, "RUNTIME", tmp_path)

    with pytest.raises(RuntimeError, match="no longer available"):
        task_filesystem.enter(["/bin/true"])
