"""Utilities for overlaying local agent packages into Modal sandbox builds.

When LOCAL_POSTHOG_CODE_MONOREPO_ROOT is set, the agent-server inside
Modal sandboxes is built from the local Twig monorepo instead of the
published npm package.  This lets developers iterate on agent-server
changes without publishing first.

Only active in DEBUG mode — production always uses the registry image.
"""

from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

LOCAL_AGENT_DOCKERFILE_OVERLAY = (
    "\n# Local agent packages overlay\n"
    "COPY local-shared /local-shared\n"
    "COPY local-git /local-git\n"
    "COPY local-agent /local-agent\n"
    "RUN cd /local-shared && pnpm pack && \\\n"
    '    cd /local-git && sed -i \'s/"@posthog\\/shared": "workspace:\\*"/"@posthog\\/shared": '
    '"file:\\/local-shared\\/posthog-shared-1.0.0.tgz"/\' package.json && pnpm pack && \\\n'
    '    cd /local-agent && sed -i \'s/"@posthog\\/shared": "workspace:\\*"/"@posthog\\/shared": '
    '"file:\\/local-shared\\/posthog-shared-1.0.0.tgz"/\' package.json && \\\n'
    '    sed -i \'s/"@posthog\\/git": "workspace:\\*"/"@posthog\\/git": '
    '"file:\\/local-git\\/posthog-git-1.0.0.tgz"/\' package.json && pnpm pack && \\\n'
    "    cd /scripts && pnpm install /local-agent/*.tgz && \\\n"
    "    rm -rf /local-agent /local-shared /local-git\n"
)


def get_local_posthog_code_packages() -> tuple[Path, Path, Path] | None:
    """Return (agent, shared, git) package paths from LOCAL_POSTHOG_CODE_MONOREPO_ROOT, or None.

    Only returns paths in DEBUG mode for local development.
    """
    if not settings.DEBUG:
        return None

    monorepo_root = os.environ.get("LOCAL_POSTHOG_CODE_MONOREPO_ROOT", os.environ.get("LOCAL_TWIG_MONOREPO_ROOT", ""))
    if not monorepo_root or not Path(monorepo_root).is_dir():
        return None

    root = Path(monorepo_root).resolve()
    agent = root / "packages" / "agent"
    shared = root / "packages" / "shared"
    git = root / "packages" / "git"

    missing = [name for name, p in [("agent", agent), ("shared", shared), ("git", git)] if not p.is_dir()]
    if missing:
        logger.warning(f"LOCAL_POSTHOG_CODE_MONOREPO_ROOT set but missing packages: {missing}")
        return None

    return agent, shared, git


def overlay_local_packages(context_dir: Path, dockerfile_path: Path) -> bool:
    """Copy local agent packages into the build context and append Dockerfile steps.

    Returns True if the overlay was applied, False otherwise.
    """
    local_pkgs = get_local_posthog_code_packages()
    if not local_pkgs:
        return False

    agent_path, shared_path, git_path = local_pkgs
    ignore = shutil.ignore_patterns("node_modules", ".turbo")
    shutil.copytree(agent_path, context_dir / "local-agent", ignore=ignore)
    shutil.copytree(shared_path, context_dir / "local-shared", ignore=ignore)
    shutil.copytree(git_path, context_dir / "local-git", ignore=ignore)

    with open(dockerfile_path, "a") as f:
        f.write(LOCAL_AGENT_DOCKERFILE_OVERLAY)

    logger.info("Modal build context includes local agent packages from LOCAL_POSTHOG_CODE_MONOREPO_ROOT")
    return True
