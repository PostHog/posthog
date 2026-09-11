"""Which repository file each Storybook snapshot renders, read from the run's build artifact.

A snapshot identifier is built from a story id, and only the Storybook build knows which file a
story came from. The build uploads its story index as a GitHub Actions artifact, so the index of the
run behind the current baseline is the map from a snapshot back to a file somebody owns.

Nothing is stored. The artifact of one workflow run never changes, so a parsed index is cached under
that run id and the key rotates on its own when the baseline moves.
"""

from __future__ import annotations

import io
import json
import zipfile
import posixpath
from collections.abc import Mapping

from django.core.cache import cache

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationError

from ..models import Repo
from . import errors, github_api

logger = structlog.get_logger(__name__)

# These mirror the snapshot naming in common/storybook/.storybook/test-runner.ts. An identifier is
# "<story id>--<theme>", with "--<browser>" appended for a browser other than chromium, and the
# story id carries "--<width>" for a story that snapshots several viewport widths.
_THEMES = ("light", "dark")
_SUFFIXED_BROWSERS = ("webkit",)
_VIEWPORT_WIDTHS = ("narrow", "medium", "wide", "superwide")

# Where the PostHog repository builds Storybook, and the artifact its workflow uploads the build as.
STORYBOOK_ARTIFACT_NAME = "storybook-build"
STORYBOOK_PACKAGE_DIR = "common/storybook"

_INDEX_MEMBER = "index.json"
# The zip is tens of megabytes, so it needs far longer than an API read.
_ZIP_TIMEOUT_SECONDS = 60
# Both are read into memory whole, so an artifact far past the size of a real build is refused
# rather than made the worker's problem.
_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_MAX_INDEX_BYTES = 32 * 1024 * 1024
_CACHE_TTL_SECONDS = 2 * 24 * 60 * 60


@frozen
class StoryIndex:
    """The story-to-file map of one Storybook build."""

    path_by_story_id: Mapping[str, str]


def _strip_theme_and_browser(identifier: str) -> str | None:
    """The story id an identifier was built from, before any width suffix is considered.

    None when the identifier carries no theme, which means the test runner did not write it.
    """
    rest = identifier
    for browser in _SUFFIXED_BROWSERS:
        if rest.endswith(f"--{browser}"):
            rest = rest.removesuffix(f"--{browser}")
            break
    for theme in _THEMES:
        if rest.endswith(f"--{theme}"):
            return rest.removesuffix(f"--{theme}")
    return None


def story_path(index: StoryIndex, identifier: str) -> str | None:
    """The repository path behind one snapshot identifier, or None when the index has no such story.

    The full story id is looked up first, because a story can be named after a viewport width
    ("lemon-ui-lemon-banner--narrow" is a story of its own). Stripping the width first would place
    that snapshot in the file of a different story.
    """
    story_id = _strip_theme_and_browser(identifier)
    if story_id is None:
        return None
    path = index.path_by_story_id.get(story_id)
    if path is not None:
        return path
    for width in _VIEWPORT_WIDTHS:
        if story_id.endswith(f"--{width}"):
            return index.path_by_story_id.get(story_id.removesuffix(f"--{width}"))
    return None


def _parse_story_index(raw: bytes, package_dir: str) -> dict[str, str]:
    """Story id to repository path, for the story entries of a Storybook index.

    Raises ValueError when the payload is not a story index. `json.JSONDecodeError` is a ValueError,
    so a truncated download lands in the same branch.
    """
    document = json.loads(raw)
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("storybook index has no entries")

    paths: dict[str, str] = {}
    for story_id, entry in entries.items():
        # Docs pages carry an importPath too, and no snapshot is taken of one.
        if not isinstance(entry, dict) or entry.get("type") != "story":
            continue
        import_path = entry.get("importPath")
        if not isinstance(import_path, str) or not import_path:
            continue
        path = posixpath.normpath(posixpath.join(package_dir, import_path))
        # A story imported from outside the checkout has no repository path, so no team can own it.
        # An absolute import path drops the package directory on the join, so it lands here too.
        if path.startswith("..") or posixpath.isabs(path):
            continue
        paths[story_id] = path
    return paths


def _log_unavailable(repo: Repo, github_run_id: str, reason: str) -> None:
    logger.info(
        "visual_review.story_index_unavailable",
        repo_id=str(repo.id),
        github_run_id=github_run_id,
        reason=reason,
    )


def _fetch_index_member(repo: Repo, github_run_id: str) -> bytes | None:
    """The raw index.json of a run's Storybook artifact. None when it cannot be read."""
    listing = github_api._github_api_request(
        "GET", repo, f"actions/runs/{github_run_id}/artifacts", params={"per_page": 100}
    )
    if listing.status_code != 200:
        _log_unavailable(repo, github_run_id, "artifact_missing")
        return None

    artifact = next(
        (item for item in listing.json().get("artifacts") or [] if item.get("name") == STORYBOOK_ARTIFACT_NAME),
        None,
    )
    if artifact is None:
        _log_unavailable(repo, github_run_id, "artifact_missing")
        return None
    if artifact.get("expired"):
        _log_unavailable(repo, github_run_id, "artifact_expired")
        return None
    if (artifact.get("size_in_bytes") or 0) > _MAX_ARTIFACT_BYTES:
        _log_unavailable(repo, github_run_id, "artifact_too_large")
        return None

    # GitHub answers this with a 302 to a signed blob URL. Requests follows it and drops the
    # Authorization header on the host change, so the GitHub token never reaches the blob host.
    download = github_api._github_api_request(
        "GET", repo, f"actions/artifacts/{artifact['id']}/zip", timeout=_ZIP_TIMEOUT_SECONDS
    )
    if download.status_code != 200:
        _log_unavailable(repo, github_run_id, "download_failed")
        return None

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        if _INDEX_MEMBER not in archive.namelist():
            _log_unavailable(repo, github_run_id, "index_missing")
            return None
        if archive.getinfo(_INDEX_MEMBER).file_size > _MAX_INDEX_BYTES:
            _log_unavailable(repo, github_run_id, "artifact_too_large")
            return None
        return archive.read(_INDEX_MEMBER)


def fetch_story_index(repo: Repo, github_run_id: str) -> StoryIndex | None:
    """The story index of one workflow run's Storybook build. None means attribution is unavailable.

    Only a success is cached, so a run whose artifact was gone this morning is read again tomorrow.
    Every failure is answered with None: the digest reports what it could not attribute, and never
    fails over a missing artifact.
    """
    cache_key = f"visual_review_story_index:{repo.id}:{github_run_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return StoryIndex(path_by_story_id=cached)

    try:
        raw = _fetch_index_member(repo, github_run_id)
        if raw is None:
            return None
        paths = _parse_story_index(raw, STORYBOOK_PACKAGE_DIR)
    except errors.GitHubIntegrationNotFoundError:
        _log_unavailable(repo, github_run_id, "no_github_integration")
        return None
    except (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException, zipfile.BadZipFile):
        _log_unavailable(repo, github_run_id, "download_failed")
        return None
    except ValueError:
        _log_unavailable(repo, github_run_id, "index_invalid")
        return None

    cache.set(cache_key, paths, timeout=_CACHE_TTL_SECONDS)
    return StoryIndex(path_by_story_id=paths)
