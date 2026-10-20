from unittest import TestCase

from products.mcp_analytics.backend.management.commands.seed_mcp_sessions import EvenPicker


class TestEvenPicker(TestCase):
    def test_key_whose_weight_drops_to_zero_is_not_picked_despite_its_deficit(self) -> None:
        picker: EvenPicker[str] = EvenPicker()
        assert picker.pick({"legacy": 0.5, "stateless": 0.5}) == "legacy"

        assert picker.pick({"legacy": 1, "stateless": 0}, amount=0.1) == "legacy"
