import pytest
from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import SignalReport
from products.signals.backend.report_tags import set_report_tags, union_report_tags


class TestSetReportTags(BaseTest):
    def setUp(self):
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, tags=["billing", "api"])

    @parameterized.expand(
        [
            ("omitted_keeps_the_set", None, False, ["billing", "api"]),
            ("list_replaces_the_set", ["Cost Spike", "cost_spike", "web"], True, ["cost-spike", "web"]),
            ("empty_list_clears_the_set", [], True, []),
            ("same_set_writes_nothing", ["billing", "API"], False, ["billing", "api"]),
        ]
    )
    def test_set_report_tags(self, _name: str, tags: list[str] | None, changed: bool, expected: list[str]):
        assert set_report_tags(self.report, tags) is changed

        self.report.refresh_from_db()
        assert self.report.tags == expected

    @parameterized.expand(
        [
            ("too_many", [f"tag-{i}" for i in range(SignalReport.MAX_TAGS + 1)]),
            ("empty_after_normalization", ["!!!"]),
            ("too_long", ["x" * (SignalReport.MAX_TAG_LENGTH + 1)]),
        ]
    )
    def test_invalid_tags_are_rejected_and_keep_the_set(self, _name: str, tags: list[str]):
        with pytest.raises(ValueError):
            set_report_tags(self.report, tags)

        self.report.refresh_from_db()
        assert self.report.tags == ["billing", "api"]


class TestUnionReportTags(SimpleTestCase):
    def test_union_keeps_first_seen_order_and_caps_the_count(self):
        survivor = [f"own-{i}" for i in range(8)]
        source = ["own-0", "src-a", "src-b", "src-c"]

        assert union_report_tags(survivor, source) == [*survivor, "src-a", "src-b"]
