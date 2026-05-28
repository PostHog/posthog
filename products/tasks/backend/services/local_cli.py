"""Build and cache the local ``posthog-cli`` binary for bind-mounting into sandboxes.

Mirrors ``local_skills.py``: the sandbox image does not ship ``posthog-cli`` and
has no Rust toolchain, so for eval/local runs we build the binary once from the
**current working tree** (the dev version under change) and bind-mount it into the
sandbox at runtime. ``LocalCliCache`` hashes the ``cli/`` sources plus the embedded
``cli-manifest.json`` and reuses a prior build when nothing changed, so repeat
pytest invocations pay ~no cost.

Only ever used by eval/local sandbox provisioning; production sandboxes never set
``SANDBOX_LOCAL_CLI_HOST_PATH`` and so never mount a host binary.
"""

from __future__ import annotations

import json
import hashlib
import logging
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

ENV_LOCAL_CLI_HOST_PATH = "SANDBOX_LOCAL_CLI_HOST_PATH"
BUILD_HASH_FILENAME = ".posthog-cli.build-hash"
# Inputs that change the built binary. The release binary embeds cli-manifest.json
# via include_str!, so a manifest change must invalidate the cache too.
_SOURCE_GLOBS = ("cli/src", "cli/Cargo.toml", "cli/Cargo.lock")
_EMBEDDED_ARTIFACTS = ("services/mcp/schema/cli-manifest.json",)


class LocalCliBuildError(RuntimeError):
    pass


class LocalCliCache:
    """Builds ``posthog-cli`` once from the working tree and reuses it across runs."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(settings.BASE_DIR)
        self.cli_dir = self.base_dir / "cli"

    def ensure_built(self) -> Path:
        """Build the binary if sources changed; return the path to the executable."""
        binary = self._binary_path()
        source_hash = self._compute_source_hash()
        hash_file = self.cli_dir / BUILD_HASH_FILENAME

        if binary.exists() and hash_file.exists() and _read(hash_file) == source_hash:
            logger.info("posthog-cli up-to-date (hash=%s)", source_hash[:12])
            return binary

        logger.info("Building posthog-cli (release) from %s", self.cli_dir)
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=self.cli_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise LocalCliBuildError(f"cargo build failed:\n{result.stderr[-2000:]}")

        if not binary.exists():
            raise LocalCliBuildError(f"cargo build succeeded but binary not found at {binary}")

        hash_file.write_text(source_hash)
        return binary

    def _binary_path(self) -> Path:
        """Locate the release binary, honoring a relocated CARGO_TARGET_DIR."""
        target_dir = self.base_dir / "target"
        try:
            meta = subprocess.run(
                ["cargo", "metadata", "--format-version", "1", "--no-deps"],
                cwd=self.cli_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            target_dir = Path(json.loads(meta.stdout)["target_directory"])
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("cargo metadata failed (%s); assuming %s", exc, target_dir)
        return target_dir / "release" / "posthog-cli"

    def _compute_source_hash(self) -> str:
        hasher = hashlib.sha256()
        for file_path in self._iter_source_files():
            rel = file_path.relative_to(self.base_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(file_path.read_bytes())
            hasher.update(b"\0")
        return hasher.hexdigest()

    def _iter_source_files(self):
        paths: list[Path] = []
        for glob in _SOURCE_GLOBS:
            root = self.base_dir / glob
            if root.is_dir():
                paths.extend(p for p in root.rglob("*") if p.is_file())
            elif root.is_file():
                paths.append(root)
        for artifact in _EMBEDDED_ARTIFACTS:
            p = self.base_dir / artifact
            if p.is_file():
                paths.append(p)
        return sorted(paths)


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""
