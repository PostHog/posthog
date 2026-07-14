from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]


def _copy_executable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)


def test_hogli_prefers_the_current_worktree_venv(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    local_venv = worktree / ".flox/cache/venv"
    foreign_venv = tmp_path / "foreign-venv"

    _copy_executable(REPO_ROOT / "bin/hogli", worktree / "bin/hogli")
    (worktree / "tools/hogli").mkdir(parents=True)
    local_venv.joinpath("bin").mkdir(parents=True)
    foreign_venv.joinpath("bin").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(worktree)], check=True)

    fake_python = local_venv / "bin/python"
    local_venv.parent.joinpath("agent-env").write_text(
        f"export FLOX_ENV={worktree}/.flox/run/test\nexport PATH={worktree}/.flox/run/test/bin:$PATH\n"
    )
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "remaining_path=${PATH#*:}\n"
        'printf \'%s\\n\' "$VIRTUAL_ENV" "$UV_PROJECT_ENVIRONMENT" "$FLOX_ENV_PROJECT" "$FLOX_ENV" '
        '"${PATH%%:*}" "${remaining_path%%:*}" "$@"\n'
    )
    fake_python.chmod(0o755)

    foreign_hogli = foreign_venv / "bin/hogli"
    foreign_hogli.symlink_to(REPO_ROOT / "bin/hogli")
    environment = {
        **os.environ,
        "FLOX_ENV_PROJECT": str(REPO_ROOT),
        "UV_PROJECT_ENVIRONMENT": str(foreign_venv),
        "VIRTUAL_ENV": str(foreign_venv),
    }

    result = subprocess.run(
        [str(foreign_hogli), "test", "example.py"],
        cwd=worktree,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        str(local_venv),
        str(local_venv),
        str(worktree),
        str(worktree / ".flox/run/test"),
        str(local_venv / "bin"),
        str(worktree / ".flox/run/test/bin"),
        "-m",
        "hogli",
        "test",
        "example.py",
    ]


def test_with_flox_clears_an_inherited_checkout_environment(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    fake_bin = tmp_path / "fake-bin"
    _copy_executable(REPO_ROOT / "bin/with-flox", worktree / "bin/with-flox")

    fake_flox = fake_bin / "flox"
    fake_flox.parent.mkdir(parents=True)
    fake_flox.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "${FLOX_ENV_PROJECT-unset}" "${VIRTUAL_ENV-unset}" '
        '"${UV_PROJECT_ENVIRONMENT-unset}" "${_FLOX_ACTIVE_ENVIRONMENTS-unset}" "$@"\n'
    )
    fake_flox.chmod(0o755)
    environment = {
        **os.environ,
        "FLOX_ENV_PROJECT": "/foreign/repo",
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "UV_PROJECT_ENVIRONMENT": "/foreign/venv",
        "VIRTUAL_ENV": "/foreign/venv",
        "_FLOX_ACTIVE_ENVIRONMENTS": "foreign",
    }

    result = subprocess.run(
        [str(worktree / "bin/with-flox"), "true"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "unset",
        "unset",
        "unset",
        "unset",
        "activate",
        "--dir",
        str(worktree),
        "--",
        "true",
    ]


def test_setup_caches_only_the_worktree_toolchain_environment(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    _copy_executable(REPO_ROOT / "bin/setup-worktree-env", worktree / "bin/setup-worktree-env")
    subprocess.run(["git", "init", "--quiet", str(worktree)], check=True)

    fake_with_flox = worktree / "bin/with-flox"
    fake_with_flox.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' 'PATH={worktree}/.flox/run/test/bin:/usr/bin' "
        f"'FLOX_ENV_PROJECT={worktree}' 'FLOX_SENTRY_DSN=secret' 'MY_SECRET=secret'\n"
    )
    fake_with_flox.chmod(0o755)

    subprocess.run([str(worktree / "bin/setup-worktree-env")], check=True)

    cached_environment = worktree.joinpath(".flox/cache/agent-env").read_text()
    assert f"export FLOX_ENV_PROJECT={worktree}" in cached_environment
    assert f"export PATH={worktree}/.flox/run/test/bin:/usr/bin" in cached_environment
    assert "SENTRY" not in cached_environment
    assert "SECRET" not in cached_environment
