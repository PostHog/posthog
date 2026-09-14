"""Unit tests for logic/story_index.py — the story-to-file map the CLI uploads with a run."""

import json
import hashlib

import pytest
from unittest.mock import patch

from django.core.cache import cache

from posthog.storage.object_storage import ObjectStorageError

from products.visual_review.backend.facade.contracts import CreateRunInput
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import repos, runs, story_index
from products.visual_review.backend.models import Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_INDEX = story_index.StoryIndex(
    path_by_story_id={
        "scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx",
        # A story of its own whose name happens to be a viewport width name.
        "lemon-ui-lemon-banner--narrow": "frontend/src/lib/lemon-ui/LemonBannerNarrow.stories.tsx",
        "lemon-ui-lemon-banner--info": "frontend/src/lib/lemon-ui/LemonBanner.stories.tsx",
    },
)


def _map_bytes(paths: dict[str, str]) -> bytes:
    return json.dumps({"version": 1, "paths": paths}).encode()


_MAP = _map_bytes({"scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx"})
_MAP_HASH = hashlib.sha256(_MAP).hexdigest()
_OTHER_HASH = hashlib.sha256(b"another build").hexdigest()


class TestStoryPath:
    @pytest.mark.parametrize(
        "identifier,expected",
        [
            ("scenes-app-button--primary--light", "frontend/src/scenes/Button.stories.tsx"),
            ("scenes-app-button--primary--dark", "frontend/src/scenes/Button.stories.tsx"),
            ("scenes-app-button--primary--dark--webkit", "frontend/src/scenes/Button.stories.tsx"),
            # The width is only stripped once the full story id misses.
            ("lemon-ui-lemon-banner--info--superwide--light", "frontend/src/lib/lemon-ui/LemonBanner.stories.tsx"),
            # A story named after a width matches exactly, so it keeps its own file.
            ("lemon-ui-lemon-banner--narrow--light", "frontend/src/lib/lemon-ui/LemonBannerNarrow.stories.tsx"),
            ("scenes-app-gone--primary--light", None),
            # Nothing the test runner wrote looks like this, so there is no story to guess at.
            ("scenes-app-button--primary", None),
        ],
    )
    def test_resolves_an_identifier_to_its_story_file(self, identifier: str, expected: str | None) -> None:
        assert story_index.story_path(_INDEX, identifier) == expected


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestUploadedStoryIndex:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=4242, repo_full_name="org/story-index")

    def _run(self, repo, metadata: dict | None = None) -> Run:
        run, _uploads = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="master",
                snapshots=[],
                metadata=metadata or {},
            ),
            team_id=repo.team_id,
        )
        return run

    @pytest.mark.parametrize(
        "stored,asks_for_upload",
        [(False, True), (True, False)],
    )
    def test_the_first_shard_records_the_hash_and_the_map_is_asked_for_only_when_missing(
        self, repo, stored: bool, asks_for_upload: bool
    ) -> None:
        run = self._run(repo)
        with (
            patch.object(story_index.StoryIndexStorage, "exists", return_value=stored),
            patch.object(
                story_index.StoryIndexStorage,
                "get_presigned_upload_url",
                return_value={"url": "https://storage.example.com", "fields": {"key": "k"}},
            ),
        ):
            first = story_index.register_story_index(run.id, repo.team_id, _MAP_HASH)
            # A later shard reporting a different build must not replace what the first one recorded,
            # or get an upload target for a map no reader will use.
            conflicting = story_index.register_story_index(run.id, repo.team_id, _OTHER_HASH)

        run.refresh_from_db()
        assert run.metadata[story_index.METADATA_KEY] == _MAP_HASH
        assert (first is not None) is asks_for_upload
        assert conflicting is None

    def test_a_value_that_is_not_a_sha256_is_ignored(self, repo) -> None:
        run = self._run(repo)

        with patch.object(story_index.StoryIndexStorage, "exists") as exists:
            assert story_index.register_story_index(run.id, repo.team_id, "../../other-repo/map") is None

        run.refresh_from_db()
        assert story_index.METADATA_KEY not in run.metadata
        assert exists.call_count == 0

    @pytest.mark.parametrize(
        "metadata,stored,expected",
        [
            (
                {story_index.METADATA_KEY: _MAP_HASH},
                _MAP,
                story_index.StoryIndex(
                    path_by_story_id={"scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx"}
                ),
            ),
            # Bytes that do not hash to their name were not what the CLI built, so they are not trusted.
            (
                {story_index.METADATA_KEY: _MAP_HASH},
                _map_bytes({"scenes-app-button--primary": "frontend/src/Elsewhere.stories.tsx"}),
                f"the story index {_MAP_HASH[:12]} could not be read",
            ),
            ({}, _MAP, "the newest default branch Storybook run recorded no story index"),
            # A storage outage reads as an unknown owner rather than failing the page or the digest.
            (
                {story_index.METADATA_KEY: _MAP_HASH},
                ObjectStorageError("read failed"),
                f"the story index {_MAP_HASH[:12]} could not be read",
            ),
        ],
    )
    def test_reads_the_map_the_newest_run_recorded(self, repo, metadata: dict, stored: bytes, expected) -> None:
        run = self._run(repo, metadata)

        stored_read = {"side_effect": stored} if isinstance(stored, Exception) else {"return_value": stored}
        with patch.object(story_index.StoryIndexStorage, "read", **stored_read):
            result = story_index.latest_story_index(repo, {RunType.STORYBOOK: run})

        assert result == expected
