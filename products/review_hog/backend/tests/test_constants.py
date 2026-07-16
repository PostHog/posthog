from parameterized import parameterized

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.reviewer.constants import DEFAULT_URGENCY_THRESHOLD, published_priorities_for
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
        assert DEFAULT_URGENCY_THRESHOLD.value == ReviewUserSettings.UrgencyThreshold.SHOULD_FIX.value
