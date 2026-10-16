import math

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.known_patterns import IssuePatternRow, find_known_patterns

TEAM_ID = 1
NO_FRAMES = math.nan


def _row(
    issue_id: str,
    events: int,
    sessions: int,
    pattern: str,
    no_stack: float,
    third_party: float,
    resolved: float,
    own_code: float = 1.0,
    handled: float = 0.0,
    sentence: float = 0.0,
) -> IssuePatternRow:
    return IssuePatternRow(
        team_id=TEAM_ID,
        issue_id=issue_id,
        events=events,
        sessions=sessions,
        pattern=pattern,
        no_stack_share=no_stack,
        third_party_share=third_party,
        resolved_share=resolved,
        own_code_share=own_code,
        handled_share=handled,
        sentence_share=sentence,
    )


class TestFindKnownPatterns(SimpleTestCase):
    @parameterized.expand(
        [
            # name, events, pattern, third-party share, own-code, handled and sentence shares, expected reasons
            ("known_pattern", 100, "resize_observer", NO_FRAMES, (1.0, 0.0, 0.0), ["known_pattern"]),
            ("failed_request", 100, "http_status", NO_FRAMES, (1.0, 0.0, 0.0), ["known_pattern"]),
            ("first_party_code_bug", 100, "code_bug", 0.1, (1.0, 0.0, 0.0), []),
            ("code_bug_thrown_in_a_vendor_script", 100, "code_bug", 0.8, (1.0, 0.0, 0.0), ["third_party"]),
            (
                "known_pattern_in_a_vendor_script",
                100,
                "chunk_load",
                0.9,
                (1.0, 0.0, 0.0),
                ["known_pattern", "third_party"],
            ),
            ("stack_outside_the_apps_code", 100, "code_bug", NO_FRAMES, (0.2, 0.0, 0.0), ["no_own_code"]),
            ("handled_error_with_a_sentence", 100, "other", NO_FRAMES, (1.0, 0.9, 0.9), ["app_reported"]),
            # An API failure the app throws without catching it is still the app reporting a failure it expected.
            ("unhandled_error_with_a_sentence", 100, "other", NO_FRAMES, (1.0, 0.0, 0.9), ["app_reported"]),
            ("handled_error_naming_code", 100, "other", NO_FRAMES, (1.0, 0.9, 0.0), []),
            ("too_few_events", 19, "resize_observer", NO_FRAMES, (1.0, 0.0, 0.0), []),
        ]
    )
    def test_flags_issues_that_are_likely_noise(
        self,
        _name: str,
        events: int,
        pattern: str,
        third_party_share: float,
        shares: tuple[float, float, float],
        expected_reasons: list[str],
    ) -> None:
        own_code, handled, sentence = shares
        rows = [_row("issue", events, 10, pattern, 1.0, third_party_share, NO_FRAMES, own_code, handled, sentence)]

        issues = find_known_patterns(rows)[TEAM_ID]["issues"]

        self.assertEqual([issue["reasons"] for issue in issues], [expected_reasons] if expected_reasons else [])

    def test_summarizes_volume_of_every_issue_not_only_flagged_ones(self) -> None:
        rows = [
            _row("resize", 100, 40, "resize_observer", 1.0, NO_FRAMES, NO_FRAMES),
            _row("bug", 30, 20, "code_bug", 0.0, 0.0, 0.5),
            _row("rare_network", 10, 5, "network", 1.0, NO_FRAMES, NO_FRAMES),
        ]

        summary = find_known_patterns(rows)[TEAM_ID]

        self.assertEqual((summary["total_events"], summary["pattern_events"]), (140, 110))
        self.assertEqual(
            summary["classes"],
            [
                {"pattern": "resize_observer", "events": 100},
                {"pattern": "code_bug", "events": 30},
                {"pattern": "network", "events": 10},
            ],
        )
        flagged = summary["issues"]
        self.assertEqual([issue["id"] for issue in flagged], ["resize"])
        self.assertEqual((flagged[0]["third_party_share"], flagged[0]["resolved_share"]), (0.0, None))
