import os
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.publication_base import (
    TrustedBaseManifest,
    TrustedBaseTextBlob,
    TrustedBaseTreeEntry,
)
from products.tasks.backend.logic.services.publication_bundle import (
    PublicationBundleError,
    PublicationBundleLimits,
    PublicationBundlePlan,
    build_publication_bundle,
    inspect_publication_bundle,
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


def _manifest(base: str, tree: str, files: dict[str, tuple[str, str, str]]) -> TrustedBaseManifest:
    return TrustedBaseManifest(
        repository="PostHog/posthog",
        base_sha=base,
        tree_sha=tree,
        entries=tuple(
            TrustedBaseTreeEntry(path=path, mode=mode, object_type="blob", object_sha=object_id)
            for path, (mode, object_id, _) in sorted(files.items())
        ),
        old_text_blobs=tuple(
            TrustedBaseTextBlob(path=path, object_sha=object_id, text=text)
            for path, (_, object_id, text) in sorted(files.items())
        ),
    )


def _workspace(path: Path) -> tuple[str, TrustedBaseManifest]:
    _git(path, "init")
    (path / "tracked.txt").write_text("base\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "base")
    base = _git(path, "rev-parse", "HEAD")
    tree = _git(path, "rev-parse", f"{base}^{{tree}}")
    blob = _git(path, "rev-parse", f"{base}:tracked.txt")
    return base, _manifest(base, tree, {"tracked.txt": ("100644", blob, "base\n")})


def _plan(workspace: Path, root: Path, base: str, **changes: object) -> PublicationBundlePlan:
    values: dict[str, object] = {
        "workspace_path": workspace,
        "export_root": root,
        "repository": "PostHog/posthog",
        "base_commit": base,
        "commit_message": "Create proactive draft",
        "author_name": "PostHog publication service",
        "author_email": "publication@posthog.com",
        "commit_timestamp": 1_700_000_000,
        "pr_title": "Proactive draft",
        "pr_body": "Server-authored draft body",
    }
    values.update(changes)
    return PublicationBundlePlan(**values)  # type: ignore[arg-type]


def test_artifact_squashes_committed_staged_unstaged_and_untracked_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, manifest = _workspace(workspace)
    (workspace / "agent.txt").write_text("committed\n")
    _git(workspace, "add", "agent.txt")
    _git(workspace, "commit", "-m", "agent")
    (workspace / "tracked.txt").write_text("staged\n")
    _git(workspace, "add", "tracked.txt")
    (workspace / "tracked.txt").write_text("unstaged\n")
    (workspace / "new.txt").write_text("untracked\n")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)

    bundle = build_publication_bundle(plan)
    result = validate_publication_bundle(bundle.bundle_path.read_bytes(), plan, manifest)

    assert result.parent_commits == ()
    assert {item.path for item in result.files} == {"agent.txt", "new.txt", "tracked.txt"}
    assert {item.path: item.text for item in result.added_text_blobs}["tracked.txt"] == "unstaged\n"


def test_artifact_records_deletion_and_rename_against_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, manifest = _workspace(workspace)
    (workspace / "tracked.txt").rename(workspace / "renamed.txt")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)

    result = validate_publication_bundle(build_publication_bundle(plan).bundle_path.read_bytes(), plan, manifest)

    assert [(item.path, item.status) for item in result.files] == [
        ("renamed.txt", "added"),
        ("tracked.txt", "deleted"),
    ]


@pytest.mark.parametrize("mutation", ["merge", "alternates", "filter_config", "config_symlink"])
def test_rejects_unsafe_workspace_state(tmp_path: Path, mutation: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, _ = _workspace(workspace)
    if mutation == "merge":
        _git(workspace, "checkout", "-b", "feature")
        (workspace / "f.txt").write_text("f\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "f")
        _git(workspace, "checkout", "master")
        (workspace / "m.txt").write_text("m\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "m")
        _git(workspace, "merge", "feature", "--no-ff", "-m", "merge")
    elif mutation == "alternates":
        path = workspace / ".git" / "objects" / "info" / "alternates"
        path.parent.mkdir(exist_ok=True)
        path.write_text("/tmp/object-store\n")
    elif mutation == "filter_config":
        _git(workspace, "config", "filter.evil.clean", "./evil")
    else:
        config = workspace / ".git" / "config"
        target = workspace / "config"
        target.write_text(config.read_text())
        config.unlink()
        config.symlink_to(target)
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError):
        build_publication_bundle(_plan(workspace, root, base))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "binary", "generated", "oversized", "secret"])
def test_rejects_unsafe_changed_file(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, _ = _workspace(workspace)
    if kind == "symlink":
        (workspace / "bad").symlink_to("tracked.txt")
    elif kind == "hardlink":
        os.link(workspace / "tracked.txt", workspace / "bad.txt")
    elif kind == "binary":
        (workspace / "bad.txt").write_bytes(b"bad\0")
    elif kind == "generated":
        (workspace / "node_modules").mkdir()
        (workspace / "node_modules" / "bad.js").write_text("x")
    elif kind == "secret":
        (workspace / "bad.txt").write_text("github_pat_abcdefghijklmnopqrstuvwxyz1234567890")
    else:
        (workspace / "bad.txt").write_text("x" * 64)
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    limits = PublicationBundleLimits(max_file_bytes=32) if kind == "oversized" else PublicationBundleLimits()

    with pytest.raises(PublicationBundleError):
        build_publication_bundle(_plan(workspace, root, base, limits=limits))


def test_bundle_size_does_not_include_large_base_history(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    (workspace / "history.bin").write_bytes(os.urandom(1_500_000))
    _git(workspace, "add", "history.bin")
    _git(workspace, "commit", "-m", "history")
    (workspace / "tracked.txt").write_text("base\n")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "base")
    base = _git(workspace, "rev-parse", "HEAD")
    tree = _git(workspace, "rev-parse", f"{base}^{{tree}}")
    tracked = _git(workspace, "rev-parse", f"{base}:tracked.txt")
    manifest = _manifest(base, tree, {"tracked.txt": ("100644", tracked, "base\n")})
    (workspace / "tracked.txt").write_text("small change\n")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)

    bundle = build_publication_bundle(plan)

    assert bundle.byte_count < 100_000
    assert validate_publication_bundle(bundle.bundle_path.read_bytes(), plan, manifest).files[0].path == "tracked.txt"


def test_persisted_timestamp_makes_retries_identical(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, _ = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)

    first = build_publication_bundle(plan)
    second = build_publication_bundle(plan)

    assert first.head_commit == second.head_commit
    assert first.bundle_path.read_bytes() == second.bundle_path.read_bytes()


def test_inspector_rejects_a_pack_with_noncanonical_object_count_before_import(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, _ = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)
    artifact = bytearray(build_publication_bundle(plan).bundle_path.read_bytes())
    pack_offset = artifact.index(b"\n\nPACK") + 2
    artifact[pack_offset + 8 : pack_offset + 12] = (4).to_bytes(4, "big")

    with pytest.raises(PublicationBundleError, match="canonical artifact objects"):
        inspect_publication_bundle(bytes(artifact), plan)


def test_rejects_more_deletions_than_the_changed_entry_cap(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    for index in range(3):
        (workspace / f"deleted-{index}.txt").write_text("base\n")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "base")
    base = _git(workspace, "rev-parse", "HEAD")
    for index in range(3):
        (workspace / f"deleted-{index}.txt").unlink()
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError):
        build_publication_bundle(_plan(workspace, root, base, limits=PublicationBundleLimits(max_changed_files=2)))


def test_rejects_non_github_length_base_sha(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, _ = _workspace(workspace)
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)

    with pytest.raises(PublicationBundleError):
        _plan(workspace, root, base + "0" * 24)


def test_validator_rejects_wrong_base_manifest_and_timestamp(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    base, manifest = _workspace(workspace)
    (workspace / "tracked.txt").write_text("changed\n")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    plan = _plan(workspace, root, base)
    artifact = build_publication_bundle(plan).bundle_path.read_bytes()

    with pytest.raises(PublicationBundleError):
        validate_publication_bundle(
            artifact,
            plan,
            TrustedBaseManifest(
                repository=manifest.repository,
                base_sha=manifest.base_sha,
                tree_sha="0" * 40,
                entries=manifest.entries,
                old_text_blobs=manifest.old_text_blobs,
            ),
        )
    with pytest.raises(PublicationBundleError):
        validate_publication_bundle(artifact, _plan(workspace, root, base, commit_timestamp=1_700_000_001), manifest)
