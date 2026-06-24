"""Build and cache local agent skills for bind-mounting into sandboxes.

Sandbox images bake skills in at Dockerfile-COPY time, which is cheap in CI
(skills are pre-built by the release workflow) but painful for local dev:
every skill edit otherwise forces a full image rebuild. For local runs we
instead build skills into `products/posthog_ai/dist/skills/` and bind-mount
that directory into the sandbox at runtime, bypassing the image layer
entirely.

`LocalSkillsCache` is the entry point — it hashes the `products/*/skills/`
source trees and reuses a prior build when nothing has changed, so repeat
pytest invocations pay ~no cost. It only ever reads rendered output from
`products/posthog_ai/dist/skills/`; `.agents/skills/` is the user's own
Claude Code workspace and must not be sourced into sandboxed runs.

`populate_skills_directory` copies the rendered `dist/skills/` into a
destination directory — used by the Modal build-context path.
"""

from __future__ import annotations

import os
import shutil
import hashlib
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

BUILT_SKILLS_RELATIVE_PATH = Path("products/posthog_ai/dist/skills")
BUILD_HASH_FILENAME = ".build-hash"
ENV_LOCAL_SKILLS_HOST_PATH = "SANDBOX_LOCAL_SKILLS_HOST_PATH"


def _copy_directory_contents(source: Path, destination: Path) -> None:
    """Merge-copy source into destination, skipping __pycache__."""
    if not source.exists():
        return

    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name == "__pycache__":
            continue

        target = destination / child.name
        if child.is_dir():
            shutil.copytree(
                child,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def populate_skills_directory(destination: Path, base_dir: Path | None = None) -> None:
    """Copy rendered skills from ``products/posthog_ai/dist/skills/`` into ``destination``.

    Requires the dist directory to already be populated (by
    ``hogli build:skills`` or CI). Does not fall back to raw source trees:
    Jinja2 templates there would land unrendered, and ``.agents/skills/``
    is reserved for the user's local Claude Code workspace.
    """
    root = base_dir or Path(settings.BASE_DIR)
    built_skills_dir = root / BUILT_SKILLS_RELATIVE_PATH
    if built_skills_dir.exists() and any(f for f in built_skills_dir.iterdir() if f.name != BUILD_HASH_FILENAME):
        logger.info("Using pre-built skills from %s", built_skills_dir)
        _copy_directory_contents(built_skills_dir, destination)
        return

    logger.warning("No rendered skills at %s; destination will be empty", built_skills_dir)


class LocalSkillsCache:
    """Builds local skills once and reuses the output across runs.

    The cache key is a SHA-256 over the contents of every skill source file
    plus the renderer script itself, so any edit invalidates the cache
    automatically — no manual busting required.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(settings.BASE_DIR)
        self.dist_dir = self.base_dir / BUILT_SKILLS_RELATIVE_PATH
        self.hash_file = self.dist_dir / BUILD_HASH_FILENAME

    def ensure_built(self) -> Path:
        """Build skills if source changed; return ``dist/skills``.

        Priority:

        1. Content hash matches last build → reuse ``dist/skills`` as-is.
        2. In-process build succeeds → use its fresh output.
        3. Build fails but ``dist/skills`` is already populated → reuse it
           with a warning. Keeps things working when the renderer breaks
           for unrelated reasons.
        4. Otherwise raise.

        Never falls back to ``.agents/skills/`` — that directory is the
        user's local Claude Code workspace and has nothing to do with
        sandboxed runs.
        """
        source_hash = self._compute_source_hash()
        if self._is_up_to_date(source_hash):
            logger.info("Local skills up-to-date (hash=%s)", source_hash[:12])
            return self.dist_dir

        logger.info("Building local skills → %s", self.dist_dir)
        try:
            self._build(source_hash)
            return self.dist_dir
        except Exception as exc:
            logger.warning("Local skill build failed: %s", exc)

        if self._has_existing_output():
            logger.warning("Falling back to existing %s", self.dist_dir)
            # Pin the current source hash to the existing output so the
            # next run with unchanged sources skips the (failing) subprocess
            # retry. When sources do change, the hash mismatches and we
            # attempt the build again — same self-healing as the happy
            # path.
            try:
                self.hash_file.write_text(source_hash)
            except OSError as write_exc:
                logger.warning("Could not pin hash after fallback: %s", write_exc)
            return self.dist_dir

        raise RuntimeError(f"No rendered local skills at {self.dist_dir}. Run `hogli build:skills` to populate it.")

    def _has_skill_files(self) -> bool:
        """Check whether ``dist_dir`` contains any files besides the hash marker."""
        if not self.dist_dir.exists():
            return False
        return any(f for f in self.dist_dir.iterdir() if f.name != BUILD_HASH_FILENAME)

    def _has_existing_output(self) -> bool:
        return self._has_skill_files()

    def _is_up_to_date(self, source_hash: str) -> bool:
        if not self._has_skill_files():
            return False
        if not self.hash_file.exists():
            return False
        try:
            return self.hash_file.read_text().strip() == source_hash
        except OSError:
            return False

    def _build(self, source_hash: str) -> None:
        from products.posthog_ai.scripts.build_skills import SkillBuilder

        builder = SkillBuilder(self.base_dir, self.base_dir / "products", self.base_dir / "products" / "posthog_ai")
        manifest = builder.build_all()
        if not manifest.resources:
            raise RuntimeError("build_skills produced no skills")

        self.dist_dir.mkdir(parents=True, exist_ok=True)
        self.hash_file.write_text(source_hash)

    def _compute_source_hash(self) -> str:
        hasher = hashlib.sha256()
        for file_path in self._iter_source_files():
            rel = file_path.relative_to(self.base_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            try:
                hasher.update(file_path.read_bytes())
            except OSError:
                continue
            hasher.update(b"\0")
        return hasher.hexdigest()

    def _iter_source_files(self) -> list[Path]:
        roots: list[Path] = []
        products_dir = self.base_dir / "products"
        if products_dir.exists():
            for product in sorted(products_dir.iterdir()):
                skills_dir = product / "skills"
                if skills_dir.is_dir():
                    roots.append(skills_dir)

        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
                for name in sorted(filenames):
                    if name == ".gitignore":
                        continue
                    files.append(Path(dirpath) / name)

        builder_script = self.base_dir / "products" / "posthog_ai" / "scripts" / "build_skills.py"
        if builder_script.exists():
            files.append(builder_script)

        return sorted(files)
