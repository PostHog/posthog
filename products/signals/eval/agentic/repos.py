"""Registry of representative open-source repositories used by the evals.

Repo selection and implementation evals need real, recognizable codebases as
candidates and as the working tree a coding agent edits. We pin a small set of
popular OSS projects (broad enough to cover web app, infra, SDK, and library
domains) at fixed commits so cases are reproducible.

The registry is pure data plus two helpers:

- :func:`checkout` shallow-clones a repo at its pinned ref into a local cache
  (live mode only; never called by deterministic tests).
- :func:`sandbox_mount_map` renders the ``SANDBOX_REPO_MOUNT_MAP`` env value so a
  local Docker sandbox bind-mounts the checkout instead of cloning over the network.

``full_name`` is stored lowercased to match how the production repo-selection cache
and prompt normalize candidate names.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CACHE_DIR = Path(os.environ.get("SIGNALS_EVAL_REPO_CACHE", str(Path.home() / ".cache" / "signals-eval-repos")))


@dataclass(frozen=True)
class OSSRepo:
    """A pinned open-source repository candidate."""

    key: str
    full_name: str  # lowercased owner/repo
    clone_url: str
    ref: str  # tag or commit SHA to pin
    primary_language: str
    domain: str  # one-line description matching what the selection prompt reasons over

    @property
    def owner(self) -> str:
        return self.full_name.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.full_name.split("/", 1)[1]


# A deliberately diverse candidate pool: a scheduling web app, a BaaS platform, a
# workflow-automation tool, a whiteboard SPA, a headless CMS, and PostHog's own SDKs.
# Distinct enough that repo-selection ground truth is unambiguous, popular enough to be
# representative of what real teams connect.
REGISTRY: dict[str, OSSRepo] = {
    repo.key: repo
    for repo in [
        OSSRepo(
            key="cal",
            full_name="calcom/cal.com",
            clone_url="https://github.com/calcom/cal.com.git",
            ref="v4.7.0",
            primary_language="TypeScript",
            domain="Open-source scheduling / booking platform (Calendly alternative).",
        ),
        OSSRepo(
            key="supabase",
            full_name="supabase/supabase",
            clone_url="https://github.com/supabase/supabase.git",
            ref="v1.24.09",
            primary_language="TypeScript",
            domain="Backend-as-a-service: hosted Postgres, auth, storage, realtime.",
        ),
        OSSRepo(
            key="n8n",
            full_name="n8n-io/n8n",
            clone_url="https://github.com/n8n-io/n8n.git",
            ref="n8n@1.70.0",
            primary_language="TypeScript",
            domain="Workflow automation tool with a node-based editor.",
        ),
        OSSRepo(
            key="excalidraw",
            full_name="excalidraw/excalidraw",
            clone_url="https://github.com/excalidraw/excalidraw.git",
            ref="v0.17.6",
            primary_language="TypeScript",
            domain="Virtual whiteboard / hand-drawn-style diagramming SPA.",
        ),
        OSSRepo(
            key="strapi",
            full_name="strapi/strapi",
            clone_url="https://github.com/strapi/strapi.git",
            ref="v4.25.9",
            primary_language="JavaScript",
            domain="Headless CMS with a customizable admin panel and content API.",
        ),
        OSSRepo(
            key="posthog-js",
            full_name="posthog/posthog-js",
            clone_url="https://github.com/PostHog/posthog-js.git",
            ref="v1.205.0",
            primary_language="TypeScript",
            domain="PostHog browser/JS SDK for product analytics, autocapture, session replay.",
        ),
        OSSRepo(
            key="posthog-python",
            full_name="posthog/posthog-python",
            clone_url="https://github.com/PostHog/posthog-python.git",
            ref="v3.7.0",
            primary_language="Python",
            domain="PostHog server-side Python SDK for capture, feature flags, LLM analytics.",
        ),
    ]
}


def get(key: str) -> OSSRepo:
    if key not in REGISTRY:
        raise KeyError(f"unknown OSS repo key {key!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[key]


def by_full_name(full_name: str) -> OSSRepo | None:
    target = full_name.strip().lower()
    return next((r for r in REGISTRY.values() if r.full_name == target), None)


def candidate_full_names(keys: list[str]) -> list[str]:
    """Lowercased candidate list for a repo-selection case, in registry order."""
    return [get(k).full_name for k in keys]


def checkout(repo: OSSRepo, *, cache_dir: Path | None = None, depth: int = 1) -> Path:
    """Shallow-clone ``repo`` at its pinned ref into the cache and return the path.

    Idempotent: an existing checkout at the right ref is reused. Live mode only — this
    is the one function in the module that touches the network/disk.
    """
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    dest = cache_dir / repo.key
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", str(depth), "--branch", repo.ref, repo.clone_url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def sandbox_mount_map(entries: dict[str, Path]) -> str:
    """Render ``SANDBOX_REPO_MOUNT_MAP`` from ``{full_name: host_path}``.

    The local Docker sandbox reads this to bind-mount a repo instead of cloning it, which
    is how a live implementation eval points the coding agent at a pinned OSS checkout.
    """
    return ",".join(f"{full_name}:{path}" for full_name, path in entries.items())
