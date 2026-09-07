import os
import json
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.publication_bundle import (
    PublicationBundleError,
    PublicationBundleLimits,
    PublicationBundlePlan,
    build_publication_bundle,
    validate_bundle_path_and_text,
    validate_publication_bundle,
)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgSign=false", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        },
    )
    return result.stdout.strip()


def _workspace(path: Path) -> str:
    _git(path, "init")
    (path / "tracked.txt").write_text("base\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "base")
    return _git(path, "rev-parse", "HEAD")


def _plan(workspace: Path, root: Path, base: str, **changes: object) -> PublicationBundlePlan:
    values: dict[str, object] = {
        "workspace_path": workspace,
        "export_root": root,
        "repository": "PostHog/posthog",
        "base_commit": base,
        "commit_message": "feat(tasks): publish fixture",
        "commit_timestamp": 1_700_000_000,
    }
    values.update(changes)
    return PublicationBundlePlan(**values)  # type: ignore[arg-type]


def test_real_workspace_exports_normalized_text_and_exact_trees(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    (workspace / "new.txt").write_text("new\n")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)
    plan = _plan(workspace, export_root, base)

    artifact = build_publication_bundle(plan)
    validated = validate_publication_bundle(artifact.bundle_path.read_bytes(), plan)

    assert [(item.path, item.content) for item in validated.operations] == [
        ("new.txt", b"new\n"),
        ("tracked.txt", b"changed\n"),
    ]
    assert validated.base_tree_sha == _git(workspace, "rev-parse", f"{base}^{{tree}}")
    assert validated.head_tree_sha != validated.base_tree_sha


def test_malformed_pack_is_rejected_before_operations_are_returned(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)
    plan = _plan(workspace, export_root, base)
    payload = bytearray(build_publication_bundle(plan).bundle_path.read_bytes())
    pack = payload.index(b"\n\nPACK") + 2
    payload[pack + 8 : pack + 12] = (4).to_bytes(4, "big")

    with pytest.raises(PublicationBundleError):
        validate_publication_bundle(bytes(payload), plan)


def test_bundle_over_transport_limit_is_rejected_before_import(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)
    source_plan = _plan(workspace, export_root, base)
    payload = build_publication_bundle(source_plan).bundle_path.read_bytes()
    validation_plan = _plan(
        workspace,
        export_root,
        base,
        limits=PublicationBundleLimits(max_bundle_bytes=len(payload) - 1),
    )

    with pytest.raises(PublicationBundleError, match="size"):
        validate_publication_bundle(payload, validation_plan)


@pytest.mark.parametrize("kind", ["oversized", "binary", "secret", "submodule"])
def test_unsafe_workspace_content_fails_before_bundle_export(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    limits = PublicationBundleLimits(max_blob_bytes=16)
    if kind == "oversized":
        (workspace / "bad.txt").write_text("x" * 17)
    elif kind == "binary":
        (workspace / "bad.txt").write_bytes(b"binary\x00data")
    elif kind == "secret":
        (workspace / "bad.txt").write_text("ghp_abcdefghijklmnopqrstuvwxyz1234567890")
    else:
        _git(workspace, "update-index", "--add", "--cacheinfo", f"160000,{base},module")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError):
        build_publication_bundle(_plan(workspace, export_root, base, limits=limits))


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "nested/../../escape", "nested\\escape"])
def test_validator_rejects_unsafe_manifest_paths(path: str) -> None:
    with pytest.raises(PublicationBundleError):
        validate_bundle_path_and_text(path=path, text="safe synthetic content")


def test_validator_rejects_an_unsafe_delete_path_in_a_forged_bundle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / "tracked.txt").unlink()
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)
    plan = _plan(workspace, export_root, base)
    artifact = build_publication_bundle(plan)
    repository = tmp_path / "forged"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "fetch", str(artifact.bundle_path), "refs/publication-artifact/head")
    _git(repository, "checkout", "--orphan", "forged")
    manifest = json.loads(_git(repository, "show", "FETCH_HEAD:manifest.json"))
    manifest["operations"][0]["path"] = "../escape"
    (repository / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    _git(repository, "add", "manifest.json")
    _git(repository, "commit", "-m", "forged")
    _git(repository, "update-ref", "refs/publication-artifact/head", "HEAD")
    forged = tmp_path / "forged.bundle"
    _git(repository, "bundle", "create", str(forged), "refs/publication-artifact/head")

    with pytest.raises(PublicationBundleError, match="unsafe"):
        validate_publication_bundle(forged.read_bytes(), plan)


def test_workspace_git_config_with_command_surface_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    _git(workspace, "config", "core.fsmonitor", "/tmp/untrusted-command")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError, match="normalization"):
        build_publication_bundle(_plan(workspace, export_root, base))


def test_repository_excludes_cannot_hide_a_new_secret(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base = _workspace(workspace)
    (workspace / ".git" / "info" / "exclude").write_text("hidden.txt\n")
    (workspace / "hidden.txt").write_text("ghp_abcdefghijklmnopqrstuvwxyz1234567890")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError, match="normalization"):
        build_publication_bundle(_plan(workspace, export_root, base))
