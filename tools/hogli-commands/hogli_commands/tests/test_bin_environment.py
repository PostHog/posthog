from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[4]


def _copy_executable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _create_repo(tmp_path: Path, scripts: tuple[str, ...]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    for script in scripts:
        _copy_executable(REPO_ROOT / script, repo / script)
    (repo / ".flox/env").mkdir(parents=True)
    (repo / ".flox/env/manifest.toml").write_text("version = 1\n")
    (repo / "tools/hogli").mkdir(parents=True)
    (repo / "uv.lock").touch()
    _run_git(repo, "add", ".")
    _run_git(
        repo,
        "-c",
        "user.name=PostHog Test",
        "-c",
        "user.email=test@posthog.com",
        "commit",
        "--quiet",
        "-m",
        "test fixture",
    )
    return repo


def _create_worktree(repo: Path, destination: Path) -> Path:
    _run_git(repo, "worktree", "add", "--quiet", "-b", "test-worktree", str(destination))
    return destination


def _write_fake_python(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' {output}\n")
    path.chmod(0o755)


def _write_agent_env(repo: Path, content: str = "") -> None:
    manifest_hash = subprocess.run(
        ["git", "hash-object", str(repo / ".flox/env/manifest.toml")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    agent_env = repo / ".flox/cache/agent-env"
    agent_env.parent.mkdir(parents=True, exist_ok=True)
    agent_env.write_text(
        f"export POSTHOG_AGENT_ENV_VERSION=2\nexport POSTHOG_AGENT_ENV_MANIFEST={manifest_hash}\n{content}"
    )


def test_hogli_prefers_a_linked_worktree_venv(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli", "bin/helpers/worktree-borrow.sh"))
    worktree = _create_worktree(repo, tmp_path / "worktree")
    local_venv = worktree / ".flox/cache/venv"
    foreign_venv = tmp_path / "foreign-venv"

    _write_fake_python(
        local_venv / "bin/python",
        '"$VIRTUAL_ENV" "$UV_PROJECT_ENVIRONMENT" "$FLOX_ENV_PROJECT" "$RUST_LOG" "$@"',
    )
    _write_agent_env(
        worktree,
        f"export FLOX_ENV_PROJECT={worktree}\nexport RUST_LOG=worktree\n",
    )
    foreign_hogli = foreign_venv / "bin/hogli"
    foreign_hogli.parent.mkdir(parents=True)
    foreign_hogli.symlink_to(repo / "bin/hogli")

    result = subprocess.run(
        [str(foreign_hogli), "test", "example.py"],
        cwd=worktree,
        env={**os.environ, "VIRTUAL_ENV": str(foreign_venv)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        str(local_venv),
        str(local_venv),
        str(worktree),
        "worktree",
        "-m",
        "hogli",
        "test",
        "example.py",
    ]


def test_hogli_does_not_trust_an_unrelated_git_repository(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli", "bin/helpers/worktree-borrow.sh"))
    local_venv = repo / ".flox/cache/venv"
    _write_fake_python(local_venv / "bin/python", '"trusted" "$@"')
    _write_agent_env(repo)

    unrelated_repo = tmp_path / "unrelated"
    unrelated_repo.mkdir()
    _run_git(unrelated_repo, "init", "--quiet")
    _copy_executable(REPO_ROOT / "bin/hogli", unrelated_repo / "bin/hogli")
    (unrelated_repo / "tools/hogli").mkdir(parents=True)
    malicious_venv = unrelated_repo / ".flox/cache/venv"
    _write_fake_python(malicious_venv / "bin/python", '"untrusted" "$@"')
    unrelated_repo.joinpath(".flox/env").mkdir(parents=True)
    unrelated_repo.joinpath(".flox/env/manifest.toml").write_text("version = 1\n")
    _write_agent_env(unrelated_repo)

    result = subprocess.run(
        [str(repo / "bin/hogli"), "--version"],
        cwd=unrelated_repo,
        env={key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"},
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["trusted", "-m", "hogli", "--version"]


def test_hogli_preserves_a_matching_active_flox_environment(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli", "bin/helpers/worktree-borrow.sh"))
    local_venv = repo / ".flox/cache/venv"
    _write_fake_python(local_venv / "bin/python", '"$RUST_LOG" "$@"')
    _write_agent_env(repo, "export RUST_LOG=stale\n")

    result = subprocess.run(
        [str(repo / "bin/hogli"), "--version"],
        cwd=repo,
        env={
            **os.environ,
            "FLOX_ENV_PROJECT": str(repo),
            "RUST_LOG": "active",
            "VIRTUAL_ENV": str(local_venv),
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["active", "-m", "hogli", "--version"]


def test_hogli_ignores_an_agent_cache_for_an_old_manifest(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli", "bin/helpers/worktree-borrow.sh"))
    local_venv = repo / ".flox/cache/venv"
    _write_fake_python(local_venv / "bin/python", '"${RUST_LOG-unset}" "$@"')
    _write_agent_env(repo, "export RUST_LOG=stale\n")
    repo.joinpath(".flox/env/manifest.toml").write_text("version = 2\n")
    environment = {
        key: value for key, value in os.environ.items() if key not in {"FLOX_ENV_PROJECT", "RUST_LOG", "VIRTUAL_ENV"}
    }
    environment["PATH"] = "/usr/bin:/bin"

    result = subprocess.run(
        [str(repo / "bin/hogli"), "--version"],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["unset", "-m", "hogli", "--version"]


def test_hogli_accepts_a_lockfile_checked_borrowed_venv(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli", "bin/helpers/worktree-borrow.sh"))
    worktree = _create_worktree(repo, tmp_path / "worktree")
    main_venv = repo / ".flox/cache/venv"
    _write_fake_python(main_venv / "bin/python", '"$UV_NO_SYNC" "$VIRTUAL_ENV" "$@"')

    result = subprocess.run(
        [str(repo / "bin/hogli"), "--version"],
        cwd=worktree,
        env={
            **os.environ,
            "UV_NO_SYNC": "1",
            "UV_PROJECT_ENVIRONMENT": str(main_venv),
            "VIRTUAL_ENV": str(main_venv),
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["1", str(main_venv), "-m", "hogli", "--version"]


def test_hogli_uses_python3_when_virtual_env_is_unset(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/hogli",))
    fake_bin = tmp_path / "fake-bin"
    _write_fake_python(fake_bin / "python3", '"system-python" "$@"')
    environment = {key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "FLOX_ENV_PROJECT"}}
    environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(repo / "bin/hogli"), "--version"],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["system-python", "-m", "hogli", "--version"]


def test_with_flox_removes_an_inherited_checkout_from_search_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    fake_bin = tmp_path / "fake-bin"
    _copy_executable(REPO_ROOT / "bin/with-flox", worktree / "bin/with-flox")

    fake_flox = fake_bin / "flox"
    fake_flox.parent.mkdir(parents=True)
    fake_flox.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "${FLOX_ENV_PROJECT-unset}" "${VIRTUAL_ENV-unset}" '
        '"$PATH" "$LIBRARY_PATH" "$MANPATH" "$@"\n'
    )
    fake_flox.chmod(0o755)
    environment = {
        **os.environ,
        "FLOX_ENV_PROJECT": "/foreign/repo",
        "FLOX_ENV": "/foreign/repo/.flox/run/test",
        "FLOX_ENV_CACHE": "/foreign/repo/.flox/cache",
        "LIBRARY_PATH": "/foreign/repo/lib:/usr/lib",
        "MANPATH": "/foreign/repo/share/man:/usr/share/man",
        "PATH": f"/foreign/repo/.flox/run/test/bin:{fake_bin}:/usr/bin:/bin:/foreign/venv/bin",
        "VIRTUAL_ENV": "/foreign/venv",
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
        f"{fake_bin}:/usr/bin:/bin",
        "/usr/lib",
        "/usr/share/man",
        "activate",
        "--dir",
        str(worktree),
        "--",
        "true",
    ]


def test_setup_does_not_copy_secrets_and_caches_toolchain_variables(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path, ("bin/setup-worktree-env", "bin/with-flox"))
    worktree = _create_worktree(repo, tmp_path / "worktree")
    repo.joinpath(".env.local").write_text("SECRET=main-checkout\n")

    fake_with_flox = worktree / "bin/with-flox"
    fake_with_flox.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' 'PATH={worktree}/.flox/run/test/bin:/usr/bin' "
        f"'FLOX_ENV_PROJECT={worktree}' 'RUST_BACKTRACE=1' 'SCCACHE_DIR=/tmp/sccache' "
        "'OPENSSL_DIR=/tmp/openssl' 'FLOX_SENTRY_DSN=secret' 'MY_SECRET=secret'\n"
    )
    fake_with_flox.chmod(0o755)

    subprocess.run([str(worktree / "bin/setup-worktree-env")], check=True)

    cached_environment = worktree.joinpath(".flox/cache/agent-env").read_text()
    assert not worktree.joinpath(".env.local").exists()
    assert "export POSTHOG_AGENT_ENV_VERSION=2" in cached_environment
    assert "export POSTHOG_AGENT_ENV_MANIFEST=" in cached_environment
    assert f"export FLOX_ENV_PROJECT={worktree}" in cached_environment
    assert "export RUST_BACKTRACE=1" in cached_environment
    assert "export SCCACHE_DIR=/tmp/sccache" in cached_environment
    assert "export OPENSSL_DIR=/tmp/openssl" in cached_environment
    assert "SENTRY" not in cached_environment
    assert "SECRET" not in cached_environment


def test_claude_hook_preserves_supported_toolchain_variables(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _copy_executable(REPO_ROOT / ".claude/hooks/setup-flox.sh", project / ".claude/hooks/setup-flox.sh")
    project.joinpath(".flox/env").mkdir(parents=True)
    project.joinpath(".flox/env/manifest.toml").write_text("version = 1\n")
    setup = project / "bin/setup-worktree-env"
    setup.parent.mkdir(parents=True)
    setup.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'PATH=/usr/bin' 'RUST_LOG=debug' 'RUST_SRC_PATH=/tmp/rust' "
        "'OPENSSL_ROOT_DIR=/tmp/openssl'\n"
    )
    setup.chmod(0o755)
    fake_bin = tmp_path / "fake-bin"
    _write_fake_python(fake_bin / "flox", "")
    claude_env_file = tmp_path / "claude-env"
    environment = {key: value for key, value in os.environ.items() if key != "FLOX_ENV_PROJECT"}
    environment.update(
        {
            "CLAUDE_CODE_REMOTE": "false",
            "CLAUDE_ENV_FILE": str(claude_env_file),
            "CLAUDE_PROJECT_DIR": str(project),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        }
    )

    subprocess.run([str(project / ".claude/hooks/setup-flox.sh")], env=environment, check=True)

    claude_environment = claude_env_file.read_text()
    assert "export RUST_LOG=debug" in claude_environment
    assert "export RUST_SRC_PATH=/tmp/rust" in claude_environment
    assert "export OPENSSL_ROOT_DIR=/tmp/openssl" in claude_environment


def test_phrocs_mcp_uses_a_local_dot_venv_without_flox(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _copy_executable(REPO_ROOT / "bin/phrocs-mcp", project / "bin/phrocs-mcp")
    project.joinpath("tools/phrocs").mkdir(parents=True)
    project.joinpath("tools/phrocs/mcp_server.py").touch()
    local_venv = project / ".venv"
    _write_fake_python(local_venv / "bin/python", '"$VIRTUAL_ENV" "$@"')

    result = subprocess.run(
        [str(project / "bin/phrocs-mcp")],
        env={key: value for key, value in os.environ.items() if key not in {"FLOX_ENV_PROJECT", "VIRTUAL_ENV"}},
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [str(local_venv), str(project / "tools/phrocs/mcp_server.py")]
