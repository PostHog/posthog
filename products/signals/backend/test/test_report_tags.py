import pytest
from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.report_tags import (
    coerce_report_tags,
    set_report_tags,
    team_tag_vocabulary,
    union_report_tags,
)


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


class TestCoerceReportTags(SimpleTestCase):
    @parameterized.expand(
        [
            ("normalizes_and_dedupes", ["Cost Spike", "cost_spike", "web"], ["cost-spike", "web"]),
            ("drops_invalid_entries", ["!!!", "x" * (SignalReport.MAX_TAG_LENGTH + 1), 7, None, "api"], ["api"]),
            (
                "keeps_the_first_entries_up_to_the_cap",
                [f"tag-{i}" for i in range(SignalReport.MAX_TAGS + 2)],
                [f"tag-{i}" for i in range(SignalReport.MAX_TAGS)],
            ),
        ]
    )
    def test_coerce_report_tags_never_raises(self, _name: str, tags: list, expected: list[str]):
        assert coerce_report_tags(tags) == expected


class TestTeamTagVocabulary(BaseTest):
    def test_counts_tags_on_live_reports_most_used_first(self):
        SignalReport.objects.create(team=self.team, tags=["billing", "api"])
        SignalReport.objects.create(team=self.team, tags=["api"])
        SignalReport.objects.create(team=self.team, tags=["web"], status=SignalReport.Status.DELETED)
        SignalReport.objects.create(team=Team.objects.create(organization=self.organization), tags=["web"])

        assert team_tag_vocabulary(self.team.id) == ["api", "billing"]
