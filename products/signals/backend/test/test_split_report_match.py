from products.signals.backend.temporal.types import SpecificityMetadata, build_split_report_match

# Two unrelated Replay Vision findings that a group wrongly matched, each with the title of
# the group it was split from. The split child must describe its own finding, not the group.
FINDING_A = "Checkout button ignores taps on mobile\nUsers on iOS cannot complete a purchase."
GROUP_A_TITLE = "Search returns stale results"

FINDING_B = "Onboarding tour freezes on step 3\nThe next button stops responding after the plan step."
GROUP_B_TITLE = "Dashboard tiles render blank"


def _split(description: str, group_title: str):
    specificity = SpecificityMetadata(pr_title=group_title, specific_enough=False, reason="different problem")
    return build_split_report_match(description, specificity)


class TestBuildSplitReportMatch:
    def test_title_and_summary_come_from_the_same_finding(self):
        match = _split(FINDING_A, GROUP_A_TITLE)

        assert match.title == "Checkout button ignores taps on mobile"
        assert match.summary == FINDING_A

    def test_summary_does_not_reference_the_group_it_was_split_from(self):
        # Regression: the summary used to be "Split from group: <group title>", pairing this
        # finding's title with another finding's summary and misrouting the reviewer.
        a = _split(FINDING_A, GROUP_A_TITLE)
        b = _split(FINDING_B, GROUP_B_TITLE)

        assert GROUP_A_TITLE not in a.summary
        assert GROUP_B_TITLE not in b.summary
        assert FINDING_B not in a.summary
        assert FINDING_A not in b.summary
