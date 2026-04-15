"""Build and cache local agent skills for bind-mounting into sandboxes.

Sandbox images bake skills in at Dockerfile-COPY time, which is cheap in CI
(skills are pre-built by the release workflow) but painful for local dev:
every skill edit otherwise forces a full image rebuild. For local runs we
instead build skills into `products/posthog_ai/dist/skills/` and bind-mount
that directory into the sandbox at runtime, bypassing the image layer
entirely.

`LocalSkillsCache` is the entry point — it hashes the skill source tree and
reuses a prior build when nothing has changed, so repeat pytest invocations
pay ~no cost. `populate_skills_directory` is the lower-level helper that
copies whatever skills are currently on disk (pre-built or source) into a
destination directory; it is also used by the Modal build-context path.
"""

from __future__ import annotations

import os
import sys
import shutil
import hashlib
import logging
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

BUILT_SKILLS_RELATIVE_PATH = Path("products/posthog_ai/dist/skills")
SOURCE_SKILLS_RELATIVE_PATHS: tuple[Path, ...] = (
    Path(".agents/skills"),
    Path("products/posthog_ai/skills"),
)
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
    """Copy skills into ``destination`` from pre-built output or sources.

    Prefers ``products/posthog_ai/dist/skills/`` when populated (built by
    ``hogli build:skills`` or CI). Falls back to the raw source trees under
    ``.agents/skills/`` and ``products/posthog_ai/skills/`` so sandbox builds
    on a fresh checkout still see something, even if unrendered.
    """
    root = base_dir or Path(settings.BASE_DIR)
    built_skills_dir = root / BUILT_SKILLS_RELATIVE_PATH
    if built_skills_dir.exists() and any(built_skills_dir.iterdir()):
        logger.info("Using pre-built skills from %s", built_skills_dir)
        _copy_directory_contents(built_skills_dir, destination)
        return

    logger.info("Built skills directory empty or missing; falling back to source trees")
    for relative_path in SOURCE_SKILLS_RELATIVE_PATHS:
        _copy_directory_contents(root / relative_path, destination)


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
        """Build skills if source changed; fall back to the best available tree.

        Priority:

        1. Content hash matches last build → reuse ``dist/skills`` as-is.
        2. Subprocess build succeeds → use its fresh output.
        3. Build fails but ``dist/skills`` is already populated → reuse it
           with a warning. Keeps the harness usable when the renderer breaks
           for unrelated environment reasons (a broken transitive dep, or
           missing DB access inside pytest).
        4. Nothing usable in ``dist/skills`` → fall back to ``.agents/skills``
           directly. Those are already-rendered markdown that can be bind-
           mounted as-is; we just lose product skills that need Jinja2
           rendering, which is acceptable for local iteration.
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
            return self.dist_dir

        agents_skills = self.base_dir / ".agents" / "skills"
        if agents_skills.exists() and any(agents_skills.iterdir()):
            logger.warning("Falling back to %s (skipping template render)", agents_skills)
            return agents_skills

        raise RuntimeError(
            f"No local skills available: build failed and neither {self.dist_dir} nor {agents_skills} is populated."
        )

    def _has_existing_output(self) -> bool:
        return self.dist_dir.exists() and any(self.dist_dir.iterdir())

    def _is_up_to_date(self, source_hash: str) -> bool:
        if not self.dist_dir.exists():
            return False
        if not any(self.dist_dir.iterdir()):
            return False
        if not self.hash_file.exists():
            return False
        try:
            return self.hash_file.read_text().strip() == source_hash
        except OSError:
            return False

    def _build(self, source_hash: str) -> None:
        # Run the builder in a subprocess. SkillBuilder pulls in Jinja2
        # helpers that use freezegun for deterministic rendering; when those
        # helpers crash mid-init (e.g. on a broken transformers version)
        # freezegun leaks a partial monkey-patch on ``time.time`` that
        # poisons the entire parent process — breaking S3 request signing,
        # freezing pytest timers, etc. Isolating the build in a child
        # process bounds the blast radius to that child.
        script = self.base_dir / "products" / "posthog_ai" / "scripts" / "build_skills.py"
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings"}
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(self.base_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"build_skills.py exited {result.returncode}\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )

        # Overlay checked-in .agents/skills/ on top of the rendered output so
        # hand-authored skills that don't go through build_skills.py still end
        # up in the same mount.
        agents_skills = self.base_dir / ".agents" / "skills"
        if agents_skills.exists():
            for child in agents_skills.iterdir():
                if child.name in {".gitignore", "__pycache__"} or not child.is_dir():
                    continue
                target = self.dist_dir / child.name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(child, target, ignore=shutil.ignore_patterns("__pycache__"))

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
        roots: list[Path] = [
            self.base_dir / ".agents" / "skills",
        ]
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
