from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS, validate_compute_rate_cards


def test_published_compute_rate_cards_are_valid() -> None:
    assert validate_compute_rate_cards(COMPUTE_RATE_CARDS) == COMPUTE_RATE_CARDS
