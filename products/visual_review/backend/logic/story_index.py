"""The story-to-file map of a repository's Storybook build.

The CLI builds the map from the build's `index.json` and uploads it once per distinct content, named
by its SHA-256. Each run records that hash in `metadata["story_index_hash"]`. Readers take the hash of
the newest default-branch Storybook run and load the map from object storage through the cache. A
hash names exactly one map, so a cached map is never stale, and nothing here depends on how long a
CI system keeps its build artifacts.
"""

from __future__ import annotations

import re
import json
import hashlib
from collections.abc import Mapping
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.enums import RunType
from ..models import Repo, Run
from ..storage import StoryIndexStorage
from . import content_cache

logger = structlog.get_logger(__name__)

# These mirror the snapshot naming in common/storybook/.storybook/test-runner.ts. An identifier is
# "<story id>--<theme>", with "--<browser>" appended for a browser other than chromium, and the
# story id carries "--<width>" for a story that snapshots several viewport widths.
_THEMES = ("light", "dark")
_SUFFIXED_BROWSERS = ("webkit",)
_VIEWPORT_WIDTHS = ("narrow", "medium", "wide", "superwide")

METADATA_KEY = "story_index_hash"
_MAP_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@frozen
class StoryIndex:
    """The story-to-file map of one Storybook build."""

    path_by_story_id: Mapping[str, str]


@frozen
class StoryIndexUpload:
    """Where the CLI posts a map that the store does not hold yet."""

    url: str
    fields: dict[str, str]


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


def register_story_index(run_id: UUID, team_id: int, story_index_hash: str) -> StoryIndexUpload | None:
    """Record the map a run's build produced, and ask for the map when the store does not hold it.

    Every shard of a run sends the same hash, so the first shard records it and the others change
    nothing. A value that is not a SHA-256 cannot name a stored map, so it is ignored.
    """
    if not _HASH_PATTERN.match(story_index_hash):
        logger.info("visual_review.story_index_hash_invalid", run_id=str(run_id))
        return None

    with transaction.atomic(using=WRITER_DB):
        run = (
            Run.objects.using(WRITER_DB)
            .select_for_update()
            .only("id", "repo_id", "metadata")
            .get(id=run_id, team_id=team_id)
        )
        metadata = run.metadata or {}
        recorded = metadata.get(METADATA_KEY)
        if recorded is None:
            run.metadata = {**metadata, METADATA_KEY: story_index_hash}
            run.save(using=WRITER_DB, update_fields=["metadata"])
        elif recorded != story_index_hash:
            # Shards of one run test one build, so two maps mean two builds fed the same run.
            logger.warning("visual_review.story_index_hash_conflict", run_id=str(run_id))

    storage = StoryIndexStorage(str(run.repo_id))
    if storage.exists(story_index_hash):
        return None
    post = storage.get_presigned_upload_url(story_index_hash)
    if post is None:
        return None
    return StoryIndexUpload(url=post["url"], fields=post["fields"])


def _read_paths(repo: Repo, story_index_hash: str) -> dict[str, str] | None:
    """Story id to repository path, from the stored map. None when the map cannot be trusted."""
    raw = StoryIndexStorage(str(repo.id)).read(story_index_hash)
    if raw is None:
        logger.info("visual_review.story_index_missing", repo_id=str(repo.id), story_index_hash=story_index_hash)
        return None
    # The CLI uploads through a presigned post, so the bytes count only once they hash to their name.
    if hashlib.sha256(raw).hexdigest() != story_index_hash:
        logger.warning(
            "visual_review.story_index_hash_mismatch", repo_id=str(repo.id), story_index_hash=story_index_hash
        )
        return None
    try:
        document = json.loads(raw)
    except ValueError:
        logger.warning("visual_review.story_index_invalid", repo_id=str(repo.id), story_index_hash=story_index_hash)
        return None
    paths = document.get("paths") if isinstance(document, dict) and document.get("version") == _MAP_VERSION else None
    if not isinstance(paths, dict):
        logger.warning("visual_review.story_index_invalid", repo_id=str(repo.id), story_index_hash=story_index_hash)
        return None
    return {story_id: path for story_id, path in paths.items() if isinstance(story_id, str) and isinstance(path, str)}


def latest_story_index(repo: Repo, newest_run_by_type: Mapping[str, Run]) -> StoryIndex | str:
    """The story index of the newest default-branch Storybook run, or a short phrase saying why there is none."""
    run = newest_run_by_type.get(RunType.STORYBOOK)
    if run is None:
        return "there is no default branch Storybook run to read"
    # Read on a query of its own because the shared default-branch universe defers `metadata`.
    metadata = Run.objects.filter(id=run.id, team_id=repo.team_id).values_list("metadata", flat=True).first()
    story_index_hash = (metadata or {}).get(METADATA_KEY)
    if not isinstance(story_index_hash, str) or not _HASH_PATTERN.match(story_index_hash):
        return "the newest default branch Storybook run recorded no story index"
    paths = content_cache.load_by_hash("story_index", story_index_hash, lambda: _read_paths(repo, story_index_hash))
    if paths is None:
        return f"the story index {story_index_hash[:12]} could not be read"
    return StoryIndex(path_by_story_id=paths)
