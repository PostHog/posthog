"""Utilities for overlaying local agent packages into sandbox builds.

When LOCAL_POSTHOG_CODE_MONOREPO_ROOT is set, the agent-server inside
sandboxes is built from the local Twig monorepo instead of the published
npm package.  This lets developers iterate on agent-server changes
without publishing first.

Only active in DEBUG mode — production always uses the registry image.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

BUILD_OUTPUT_SUBDIR = "dist"
PACKAGE_NAMES: tuple[str, ...] = ("agent", "shared", "git")
SANDBOX_NODE_MODULES_ROOT = "/scripts/node_modules/@posthog"


@dataclass(frozen=True)
class LocalPackage:
    name: str
    source_path: Path
    sandbox_install_path: str

    @property
    def build_output_path(self) -> Path:
        return self.source_path / BUILD_OUTPUT_SUBDIR

    @property
    def sandbox_build_output_path(self) -> str:
        return f"{self.sandbox_install_path}/{BUILD_OUTPUT_SUBDIR}"


def get_local_posthog_code_packages() -> tuple[LocalPackage, ...] | None:
    """Return local @posthog/{agent,shared,git} packages, or None.

    Only returns paths in DEBUG mode for local development.
    Requires each package to have a built `dist/` directory.
    """
    if not settings.DEBUG:
        return None

    monorepo_root = os.environ.get("LOCAL_POSTHOG_CODE_MONOREPO_ROOT", os.environ.get("LOCAL_TWIG_MONOREPO_ROOT", ""))
    if not monorepo_root or not Path(monorepo_root).is_dir():
        return None

    root = Path(monorepo_root).resolve()
    packages = tuple(
        LocalPackage(
            name=name,
            source_path=root / "packages" / name,
            sandbox_install_path=f"{SANDBOX_NODE_MODULES_ROOT}/{name}",
        )
        for name in PACKAGE_NAMES
    )

    if missing := [p.name for p in packages if not p.source_path.is_dir()]:
        logger.warning(f"LOCAL_POSTHOG_CODE_MONOREPO_ROOT set but missing packages: {missing}")
        return None

    if missing := [p.name for p in packages if not p.build_output_path.is_dir()]:
        logger.warning(
            "Local packages missing built %s/ directories: %s. Run `pnpm build` in the monorepo.",
            BUILD_OUTPUT_SUBDIR,
            missing,
        )
        return None

    return packages
