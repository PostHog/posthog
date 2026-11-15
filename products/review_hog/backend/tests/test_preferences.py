from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.preferences import (
    DefaultReviewMode,
    InvalidPreference,
    PreferenceSource,
    ReviewPreferences,
    ReviewProjectDefaults,
    UrgencyThreshold,
)

NO_PROJECT_DEFAULTS = ReviewProjectDefaults.resolve({})
STRICT_PROJECT = ReviewProjectDefaults.resolve({"urgency_threshold": "must_fix", "celebrate_clean_reviews": False})


class TestReviewPreferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("code_default", {}, NO_PROJECT_DEFAULTS, UrgencyThreshold.CONSIDER, PreferenceSource.DEFAULT),
            ("project_default", {}, STRICT_PROJECT, UrgencyThreshold.MUST_FIX, PreferenceSource.PROJECT),
            (
                "user_beats_project",
                {"urgency_threshold": "should_fix"},
                STRICT_PROJECT,
                UrgencyThreshold.SHOULD_FIX,
                PreferenceSource.USER,
            ),
            # Reads ignore what the schema does not know, so a renamed or broken key never fails a load.
            (
                "invalid_value_ignored",
                {"urgency_threshold": "everything", "removed_key": True},
                STRICT_PROJECT,
                UrgencyThreshold.MUST_FIX,
                PreferenceSource.PROJECT,
            ),
        ]
    )
    def test_urgency_threshold_layers(
        self,
        _name: str,
        stored: dict,
        project: ReviewProjectDefaults,
        expected: UrgencyThreshold,
        source: PreferenceSource,
    ) -> None:
        preferences = ReviewPreferences.resolve(stored, project)

        assert preferences.urgency_threshold == expected
        assert preferences.sources["urgency_threshold"] == source

    def test_personal_only_keys_ignore_project_defaults(self) -> None:
        project = ReviewProjectDefaults.resolve({"resolve_comments": True, "default_review_mode": "flash"})

        preferences = ReviewPreferences.resolve({}, project)

        assert preferences.resolve_comments is False
        assert preferences.default_review_mode == DefaultReviewMode.FOLLOW
        assert project.stored == {}

    @parameterized.expand(
        [
            ("equal_to_project_default_is_dropped", {}, {"urgency_threshold": "must_fix"}, {}),
            ("equal_to_code_default_is_dropped", {"resolve_comments": True}, {"resolve_comments": False}, {}),
            ("different_value_is_stored", {}, {"urgency_threshold": "consider"}, {"urgency_threshold": "consider"}),
            (
                "other_keys_survive",
                {"review_inbox_prs": True},
                {"celebrate_clean_reviews": True},
                {"review_inbox_prs": True, "celebrate_clean_reviews": True},
            ),
        ]
    )
    def test_writes_store_only_what_differs(self, _name: str, stored: dict, changes: dict, expected: dict) -> None:
        current = ReviewPreferences.resolve(stored, STRICT_PROJECT)

        assert current.with_changes(changes) == expected

    @parameterized.expand(
        [
            ("unknown_key", {"review_labeled_prs": False}),
            ("full_mode", {"default_review_mode": "full"}),
            ("wrong_type", {"resolve_comments": "yes"}),
        ]
    )
    def test_writes_reject_what_the_schema_does_not_allow(self, _name: str, changes: dict) -> None:
        with self.assertRaises(InvalidPreference):
            ReviewPreferences.defaults().with_changes(changes)

    def test_project_defaults_store_only_what_differs_from_code(self) -> None:
        assert STRICT_PROJECT.with_changes({"urgency_threshold": "consider"}) == {"celebrate_clean_reviews": False}
        with self.assertRaises(InvalidPreference):
            STRICT_PROJECT.with_changes({"resolve_comments": True})
