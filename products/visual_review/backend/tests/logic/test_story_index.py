"""Unit tests for logic/story_index.py — the snapshot-to-file map from the Storybook artifact."""

import io
import json
import zipfile
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.visual_review.backend.logic import errors, story_index

_ARTIFACT_NAME = story_index.STORYBOOK_ARTIFACT_NAME

_INDEX = story_index.StoryIndex(
    path_by_story_id={
        "scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx",
        # A story of its own whose name happens to be a viewport width name.
        "lemon-ui-lemon-banner--narrow": "frontend/src/lib/lemon-ui/LemonBannerNarrow.stories.tsx",
        "lemon-ui-lemon-banner--info": "frontend/src/lib/lemon-ui/LemonBanner.stories.tsx",
    },
)


def _repo() -> MagicMock:
    return MagicMock(id=uuid4())


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _response(status_code: int = 200, payload: object = None, content: bytes = b"") -> MagicMock:
    return MagicMock(status_code=status_code, content=content, json=MagicMock(return_value=payload))


def _listing(*artifacts: dict) -> MagicMock:
    return _response(payload={"artifacts": list(artifacts)})


def _index_document(entries: dict[str, dict]) -> bytes:
    return json.dumps({"v": 5, "entries": entries}).encode()


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


class TestFetchStoryIndex:
    def test_keeps_story_entries_and_turns_import_paths_into_repo_paths(self) -> None:
        entries = {
            "scenes-app-button--primary": {
                "type": "story",
                "importPath": "../../frontend/src/scenes/Button.stories.tsx",
            },
            "scenes-app-button--docs": {"type": "docs", "importPath": "../../frontend/src/scenes/Button.mdx"},
            # A story imported from outside the checkout has no repository path to own.
            "vendor-thing--default": {"type": "story", "importPath": "../../../vendor/Thing.stories.tsx"},
            # An absolute path leaves the checkout too, and it drops the package directory on join.
            "root-thing--default": {"type": "story", "importPath": "/etc/Thing.stories.tsx"},
        }
        zip_bytes = _zip_bytes({"index.json": _index_document(entries)})
        with patch(
            "products.visual_review.backend.logic.github_api._github_api_request",
            side_effect=[_listing({"name": _ARTIFACT_NAME, "id": 42}), _response(content=zip_bytes)],
        ):
            index = story_index.fetch_story_index(_repo(), "98765")

        assert index is not None
        assert dict(index.path_by_story_id) == {"scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx"}

    # Nothing here needs the database, but the product's autouse package fixture builds it, and it
    # can only do that once a test in the module asks for it.
    @pytest.mark.django_db
    def test_reads_the_artifact_once_per_workflow_run(self) -> None:
        repo = _repo()
        zip_bytes = _zip_bytes(
            {"index.json": _index_document({"a--b": {"type": "story", "importPath": "../../frontend/src/A.tsx"}})}
        )
        with patch(
            "products.visual_review.backend.logic.github_api._github_api_request",
            side_effect=[_listing({"name": _ARTIFACT_NAME, "id": 42}), _response(content=zip_bytes)],
        ) as request:
            first = story_index.fetch_story_index(repo, "98765")
            second = story_index.fetch_story_index(repo, "98765")

        assert request.call_count == 2
        assert first is not None and second is not None
        assert dict(second.path_by_story_id) == {"a--b": "frontend/src/A.tsx"}

    @pytest.mark.parametrize(
        "responses",
        [
            pytest.param([_listing()], id="artifact_missing"),
            pytest.param([_listing({"name": "other-build", "id": 7})], id="artifact_named_differently"),
            pytest.param([_listing({"name": _ARTIFACT_NAME, "id": 42, "expired": True})], id="artifact_expired"),
            pytest.param([_response(status_code=404, payload={})], id="run_gone"),
            pytest.param(
                [_listing({"name": _ARTIFACT_NAME, "id": 42}), _response(status_code=410)],
                id="download_failed",
            ),
            pytest.param(
                [
                    _listing({"name": _ARTIFACT_NAME, "id": 42}),
                    _response(content=_zip_bytes({"iframe.html": b"<html></html>"})),
                ],
                id="index_missing",
            ),
            pytest.param(
                [_listing({"name": _ARTIFACT_NAME, "id": 42}), _response(content=_zip_bytes({"index.json": b"{"}))],
                id="index_invalid",
            ),
        ],
    )
    def test_an_unreadable_artifact_is_answered_with_none_and_not_cached(self, responses: list[MagicMock]) -> None:
        repo = _repo()
        with patch(
            "products.visual_review.backend.logic.github_api._github_api_request",
            side_effect=responses * 2,
        ) as request:
            assert story_index.fetch_story_index(repo, "98765") is None
            assert story_index.fetch_story_index(repo, "98765") is None

        # Nothing was cached, so tomorrow's run asks GitHub again instead of repeating today's miss.
        assert request.call_count == len(responses) * 2

    @pytest.mark.parametrize(
        "artifact_size,max_index_bytes",
        [
            (story_index._MAX_ARTIFACT_BYTES + 1, story_index._MAX_INDEX_BYTES),
            (1000, 5),
        ],
    )
    def test_an_oversized_artifact_is_not_read(self, artifact_size: int, max_index_bytes: int) -> None:
        responses = [
            _listing({"name": _ARTIFACT_NAME, "id": 42, "size_in_bytes": artifact_size}),
            _response(content=_zip_bytes({"index.json": _index_document({})})),
        ]
        with (
            patch.object(story_index, "_MAX_INDEX_BYTES", max_index_bytes),
            patch(
                "products.visual_review.backend.logic.github_api._github_api_request",
                side_effect=responses,
            ),
        ):
            assert story_index.fetch_story_index(_repo(), "98765") is None

    @pytest.mark.parametrize(
        "error",
        [
            errors.GitHubIntegrationNotFoundError("no integration"),
            requests.ConnectionError("boom"),
        ],
    )
    def test_a_failing_github_call_does_not_raise(self, error: Exception) -> None:
        with patch(
            "products.visual_review.backend.logic.github_api._github_api_request",
            side_effect=error,
        ):
            assert story_index.fetch_story_index(_repo(), "98765") is None
