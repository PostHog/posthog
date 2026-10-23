from __future__ import annotations

import json
import shutil
import hashlib
import zipfile
import tempfile
import subprocess
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.skill_manifest import hash_skill_files

from ..log_sink import LOGS_ROOT
from .services import package_local_skills_archive


@frozen
class SkillSnapshot:
    directory: Path
    manifest_path: Path
    sha256: str
    source_sha256: str
    archive_path: Path

    @staticmethod
    def source_fingerprint(base_dir: Path, skill_source_sha256: str, *, excluded_paths: Sequence[Path] = ()) -> str:
        base_dir = base_dir.resolve()
        excluded = tuple(path.resolve() for path in excluded_paths if path.resolve().is_relative_to(base_dir))
        if base_dir in excluded:
            raise ValueError("The eval output directory cannot be the checkout root")
        digest = hashlib.sha256(skill_source_sha256.encode())
        for staged in (False, True):
            command = ["git", "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color"]
            if staged:
                command.append("--cached")
            command.extend(["--", ".", *(f":(exclude,literal){path.relative_to(base_dir)}" for path in excluded)])
            digest.update(subprocess.check_output(command, cwd=base_dir))
            digest.update(b"\0")
        untracked = subprocess.check_output(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "*.py",
                "*.j2",
                "*.json",
                "*.toml",
                "*.yaml",
                "*.yml",
            ],
            cwd=base_dir,
        )
        for name in sorted(untracked.decode().split("\0")):
            if name:
                if any((base_dir / name).is_relative_to(path) for path in excluded):
                    continue
                digest.update(name.encode())
                digest.update(b"\0")
                digest.update((base_dir / name).read_bytes())
                digest.update(b"\0")
        return digest.hexdigest()

    @classmethod
    def capture(cls, source: Path, stack: ExitStack, *, source_sha256: str, retain: bool = False) -> SkillSnapshot:
        expected = hash_skill_files(source)
        if not expected:
            raise RuntimeError("Cannot run evals with an empty skill snapshot")
        manifests = LOGS_ROOT / "skill-snapshots"
        manifests.mkdir(parents=True, exist_ok=True)
        snapshot_id = uuid4().hex
        root = (
            manifests / snapshot_id
            if retain
            else Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="posthog-eval-skills-")))
        )
        directory = root / "skills"
        shutil.copytree(source, directory, ignore=shutil.ignore_patterns(".*", "__pycache__"))
        if hash_skill_files(directory) != expected or hash_skill_files(source) != expected:
            raise RuntimeError("Skill files changed while capturing the eval snapshot")
        for path in directory.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        manifest = (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode()
        digest = hashlib.sha256(manifest).hexdigest()
        manifest_path = manifests / f"{snapshot_id}_{digest}.json"
        manifest_path.write_bytes(manifest)
        manifest_path.chmod(0o444)
        archive_path = package_local_skills_archive(directory, manifest_path.with_suffix(".zip"))
        archive_path.chmod(0o444)
        return cls(
            directory=directory,
            manifest_path=manifest_path,
            sha256=digest,
            source_sha256=source_sha256,
            archive_path=archive_path,
        )

    @classmethod
    def restore(
        cls, archive: Path, stack: ExitStack, *, expected_sha256: str, source_sha256: str, retain: bool = False
    ) -> SkillSnapshot:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="posthog-eval-restore-")))
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                relative = Path(entry.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Invalid path in the eval skill snapshot")
                if entry.is_dir():
                    continue
                destination = directory / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(entry))
        snapshot = cls.capture(directory, stack, source_sha256=source_sha256, retain=retain)
        if snapshot.sha256 != expected_sha256:
            raise RuntimeError("Saved eval skill snapshot does not match its recorded hash")
        return snapshot
