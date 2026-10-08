from unittest.mock import patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.reviewer.constants import (
    DEFAULT_URGENCY_THRESHOLD,
    REVIEW_DESIGN_PIPELINE,
    REVIEW_DESIGN_REASON_KILL_SWITCH,
    REVIEW_DESIGN_SINGLE_AGENT,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    published_priorities_for,
    reviewhog_version_for_mode,
    select_review_design,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority


class TestPublishedPrioritiesFor:
    @parameterized.expand(
        [
            # A rank inversion here silently changes what every review publishes.
            (
                "all_issues",
                IssuePriority.CONSIDER,
                {IssuePriority.CONSIDER, IssuePriority.SHOULD_FIX, IssuePriority.MUST_FIX},
            ),
            ("default", IssuePriority.SHOULD_FIX, {IssuePriority.SHOULD_FIX, IssuePriority.MUST_FIX}),
            ("strictest", IssuePriority.MUST_FIX, {IssuePriority.MUST_FIX}),
        ]
    )
    def test_threshold_selects_priorities_at_or_above(
        self, _name: str, threshold: IssuePriority, expected: set[IssuePriority]
    ) -> None:
        assert published_priorities_for(threshold) == expected

    def test_every_priority_publishes_at_the_lowest_threshold(self) -> None:
        # An IssuePriority member missing from the rank map would silently never publish anywhere.
        assert published_priorities_for(IssuePriority.CONSIDER) == set(IssuePriority)

    def test_urgency_threshold_choices_mirror_issue_priorities(self) -> None:
        # The stored setting converts via IssuePriority(value) only at build/publish — enum drift
        # would fail reviews after the full sandbox spend, so lock the mirror here instead.
        assert {c.value for c in ReviewUserSettings.UrgencyThreshold} == {p.value for p in IssuePriority}
        assert DEFAULT_URGENCY_THRESHOLD.value == ReviewUserSettings.UrgencyThreshold.CONSIDER.value


class TestSelectReviewDesign:
    @parameterized.expand(
        [
            ("flash", REVIEW_MODE_FLASH, REVIEW_DESIGN_SINGLE_AGENT),
            ("full_never_single_agent", REVIEW_MODE_FULL, REVIEW_DESIGN_PIPELINE),
        ]
    )
    def test_single_agent_runs_only_flash_turns(self, _name: str, review_mode: str, expected: str) -> None:
        choice = select_review_design(review_mode, kill_switch_on=False)
        assert choice.design == expected

    def test_the_kill_switch_flag_moves_a_fitting_flash_turn_back_to_the_pipeline(self) -> None:
        choice = select_review_design(REVIEW_MODE_FLASH, kill_switch_on=True)
        assert (choice.design, choice.reason) == (REVIEW_DESIGN_PIPELINE, REVIEW_DESIGN_REASON_KILL_SWITCH)

    def test_the_code_default_moves_every_flash_turn_back_to_the_pipeline(self) -> None:
        with patch("products.review_hog.backend.reviewer.constants.FLASH_DESIGN_DEFAULT", REVIEW_DESIGN_PIPELINE):
            choice = select_review_design(REVIEW_MODE_FLASH, kill_switch_on=False)
            assert choice.design == REVIEW_DESIGN_PIPELINE

    @parameterized.expand(
        [
            # Dashboards split Flash by version, so a v2 turn must never report the v1 id or the reverse.
            ("flash_single_agent", REVIEW_MODE_FLASH, REVIEW_DESIGN_SINGLE_AGENT, "reviewhog-flash-2-0"),
            ("flash_pipeline", REVIEW_MODE_FLASH, REVIEW_DESIGN_PIPELINE, "reviewhog-flash-1-2"),
            ("full_pipeline", REVIEW_MODE_FULL, REVIEW_DESIGN_PIPELINE, "reviewhog-full-1-2"),
        ]
    )
    def test_version_id_depends_on_mode_and_design(
        self, _name: str, review_mode: str, review_design: str, expected: str
    ) -> None:
        assert reviewhog_version_for_mode(review_mode, review_design) == expected
