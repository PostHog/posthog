from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.schema import DateRange

from products.web_analytics.backend.attribution import attribute_change
from products.web_analytics.backend.weekly_digest import DigestFilterSpec

_BREAKDOWN_PATH = "products.web_analytics.backend.attribution._breakdown_from_spec"


def _spec() -> DigestFilterSpec:
    return DigestFilterSpec(date_range=DateRange(date_from="-7d", date_to=None))


def _rows(*pairs: tuple[str, int, int]) -> list[dict]:
    return [{"value": v, "visitors_current": cur, "visitors_previous": prev} for v, cur, prev in pairs]


class TestAttributeChange(APIBaseTest):
    def test_identifies_primary_driver_and_contribution(self):
        digest = {"visitors": {"current": 9840, "previous": 12240}}
        # One return value per dimension, in _DIMENSIONS order: channel, entry page, device, country, referrer.
        side_effect = [
            _rows(("Organic Search", 4100, 6200), ("Direct", 3000, 3100)),  # channel: -2100 is the big driver
            _rows(("/blog", 2000, 2600)),  # entry page: -600
            _rows(("Desktop", 6000, 6800)),  # device: -800
            _rows(("US", 5000, 5200)),  # country: -200
            _rows(("google.com", 3000, 3400)),  # referrer: -400
        ]
        with patch(_BREAKDOWN_PATH, side_effect=side_effect):
            result = attribute_change(self.team, _spec(), digest)

        assert result is not None
        assert result.overall_delta == -2400
        driver = result.primary_driver
        assert driver is not None
        assert driver.dimension == "channel"
        assert driver.segment == "Organic Search"
        assert driver.delta == -2100
        assert driver.contribution_pct == 87.5

    def test_ignores_segments_moving_against_the_overall_change(self):
        digest = {"visitors": {"current": 9000, "previous": 10000}}  # overall drop
        side_effect = [
            _rows(("Paid", 500, 100)),  # rose during an overall drop — must be ignored
            _rows(("/x", 100, 100)),
            _rows(("Mobile", 4000, 5000)),  # -1000 genuine driver
            _rows(("US", 100, 100)),
            _rows(("direct", 100, 100)),
        ]
        with patch(_BREAKDOWN_PATH, side_effect=side_effect):
            result = attribute_change(self.team, _spec(), digest)

        assert result is not None
        assert result.primary_driver is not None
        assert result.primary_driver.segment == "Mobile"

    def test_returns_none_without_previous_period(self):
        with patch(_BREAKDOWN_PATH, return_value=[]):
            assert attribute_change(self.team, _spec(), {"visitors": {"current": 100, "previous": None}}) is None

    def test_returns_none_when_flat(self):
        with patch(_BREAKDOWN_PATH, return_value=[]):
            assert attribute_change(self.team, _spec(), {"visitors": {"current": 100, "previous": 100}}) is None
