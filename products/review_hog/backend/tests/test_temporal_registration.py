from posthog.temporal.common.registration import validate_registration

from products.review_hog.backend.facade.temporal import TEMPORAL


def test_core_accepts_the_review_temporal_declaration() -> None:
    validate_registration("review_hog", TEMPORAL)
