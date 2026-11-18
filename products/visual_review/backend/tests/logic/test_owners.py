import pytest
from unittest.mock import MagicMock, patch

from posthog.ownership.paths import UNOWNED_TEAM, PathOwnership

from products.visual_review.backend.logic import owners, story_index
from products.visual_review.backend.logic.run_queries import SnapshotKey

_BUTTON = SnapshotKey(run_type="storybook", identifier="scenes-app-button--primary--light")
_CARD = SnapshotKey(run_type="storybook", identifier="scenes-app-card--primary--dark")
_GONE = SnapshotKey(run_type="storybook", identifier="scenes-app-gone--primary--light")
_PLAYWRIGHT = SnapshotKey(run_type="playwright", identifier="scenes-app-button--primary--light")

_INDEX = story_index.StoryIndex(
    path_by_story_id={
        "scenes-app-button--primary": "frontend/src/scenes/Button.stories.tsx",
        "scenes-app-card--primary": "frontend/src/scenes/Card.stories.tsx",
    }
)


class TestOwnerTeams:
    @pytest.mark.parametrize(
        "resolved,max_paths,expected",
        [
            # A file no entry covers is unowned. A story the index lacks, or a run type with no
            # index, has no file at all, which is not the same answer.
            (True, 2, {_BUTTON: "team-replay", _CARD: UNOWNED_TEAM}),
            # Unreadable ownership files would otherwise read every file as unowned.
            (False, 2, {}),
            # More story files than the cap are never sent to the ownership lookup.
            (True, 1, {}),
        ],
    )
    def test_names_a_team_only_for_a_story_file_it_can_place(
        self, resolved: bool, max_paths: int, expected: dict
    ) -> None:
        ownership = PathOwnership(
            team_by_path={"frontend/src/scenes/Button.stories.tsx": "team-replay"}, registry={}, resolved=resolved
        )
        repo = MagicMock(repo_full_name="org/repo", team_id=7)
        with (
            patch("products.visual_review.backend.logic.story_index.latest_story_index", return_value=_INDEX),
            patch("products.visual_review.backend.logic.owners.resolve_path_owners", return_value=ownership),
            # The reader reaches the team's integration and the cache, which this test has neither of.
            patch("products.visual_review.backend.logic.owners.fetcher_for_team") as reader,
            patch.object(owners, "_MAX_OWNED_PATHS", max_paths),
        ):
            result = owners.owner_teams(repo, [_BUTTON, _CARD, _GONE, _PLAYWRIGHT], {})

        assert result == expected
        if max_paths > 1:
            assert reader.call_args.args == (7, "org/repo")
