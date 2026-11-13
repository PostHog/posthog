import datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.activity_summary.render import InboxAction, InboxActivity, InboxArtefact, InboxStrength
from products.signals.backend.personal_ranking.candidates import Candidate
from products.signals.backend.personal_ranking.config import PersonalRankingConfig
from products.signals.backend.personal_ranking.inbox_activity import (
    InboxActivityBlock,
    ReviewerExclusionArea,
    inbox_activity_block,
)
from products.signals.backend.personal_ranking.prompt import render_inbox_activity

NOW = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)


def _at(days_ago: float) -> datetime.datetime:
    return NOW - datetime.timedelta(days=days_ago)


def _acted(report_id: str, title: str, kind: str, days_ago: float = 1, **fields) -> InboxArtefact:
    return InboxArtefact(report_id=report_id, title=title, type=kind, at=_at(days_ago), **fields)


def _candidate(ref: str, report_id: str) -> Candidate:
    return Candidate(
        ref=ref,
        report_id=report_id,
        title="Report",
        summary_lead="",
        status="ready",
        priority="P2",
        pull_request_state=None,
        source_products=(),
        scout_name=None,
        created_at=NOW,
        updated_at=NOW,
        predictions=None,
        needs_you=(),
        tags=(),
        pools=(),
    )


def _config(**overrides) -> PersonalRankingConfig:
    return PersonalRankingConfig(**{"inbox_activity_lines": 10, **overrides})


class TestInboxActivityBlock(SimpleTestCase):
    def test_a_candidate_line_starts_with_its_ref_and_a_non_candidate_line_has_none(self) -> None:
        inbox = InboxActivity(
            artefacts=(
                _acted("r1", "Export job timeouts", "work_claim", days_ago=1),
                _acted("r2", "Stale flag in onboarding", "note", days_ago=2, note="still evaluated"),
            ),
        )

        block = inbox_activity_block(inbox, _config(), candidates=[_candidate("c7", "r1")])

        rendered = render_inbox_activity(block, NOW)
        assert rendered is not None
        assert '- c7 | 1d ago | "Export job timeouts" | claimed the work' in rendered
        assert '- 2d ago | "Stale flag in onboarding" | left a note: "still evaluated"' in rendered
        assert block.properties()["inbox_activity_candidate_lines"] == 1

    @parameterized.expand(
        [
            ("removed_self", "removed themselves as reviewer"),
            ("added_self", "added themselves as reviewer"),
            ("others", "changed the reviewers"),
        ]
    )
    def test_a_reviewer_correction_renders_its_direction(self, change: str, expected: str) -> None:
        inbox = InboxActivity(
            artefacts=(_acted("r1", "Batch export retries", "reviewer_corrections", reviewer_change=change),)
        )

        block = inbox_activity_block(inbox, _config(inbox_activity_min_strength=InboxStrength.TRIAGED))

        rendered = render_inbox_activity(block, NOW)
        assert rendered is not None
        assert expected in rendered

    def test_facts_below_the_minimum_strength_stay_out(self) -> None:
        inbox = InboxActivity(
            actions=(InboxAction(report_id="r1", title="Checkout drops", type="view", first_at=_at(3), last_at=_at(1)),),
            artefacts=(_acted("r2", "Export timeouts", "work_claim", days_ago=2),),
        )

        block = inbox_activity_block(inbox, _config())

        rendered = render_inbox_activity(block, NOW)
        assert rendered is not None
        assert "Checkout drops" not in rendered
        assert "Export timeouts" in rendered

    def test_the_strongest_fact_orders_the_lines_under_the_cap(self) -> None:
        inbox = InboxActivity(
            artefacts=(
                _acted("r1", "Rated report", "reviewer_corrections", days_ago=1, reviewer_change="others"),
                _acted("r2", "Acted report", "work_claim", days_ago=3),
            ),
        )

        block = inbox_activity_block(
            inbox, _config(inbox_activity_min_strength=InboxStrength.TRIAGED, inbox_activity_lines=1)
        )

        assert [line.report_ids for line in block.lines] == [frozenset({"r2"})]

    def test_an_exclusion_renders_under_the_lines_and_hides_the_instruction(self) -> None:
        block = InboxActivityBlock(
            exclusions=(
                ReviewerExclusionArea(repository="example-org/billing-service", path_prefix=""),
                ReviewerExclusionArea(repository="example-org/web", path_prefix="frontend"),
            )
        )

        rendered = render_inbox_activity(block, NOW)
        assert rendered is not None
        assert "- asked not to review: example-org/billing-service" in rendered
        assert "- asked not to review: example-org/web frontend" in rendered

    def test_a_new_rating_changes_the_hash_but_a_new_open_alone_does_not(self) -> None:
        config = _config(inbox_activity_min_strength=InboxStrength.VIEWED)
        base = InboxActivity(artefacts=(_acted("r1", "Export timeouts", "work_claim", days_ago=2),))
        with_rating = InboxActivity(
            actions=base.actions,
            artefacts=(
                *base.artefacts,
                InboxArtefact(
                    report_id="r2", title="Checkout drops", type="dismissal", at=_at(1), reason="analysis_wrong"
                ),
            ),
        )
        with_open = InboxActivity(
            actions=(
                InboxAction(report_id="r3", title="Slow dashboard", type="view", first_at=_at(3), last_at=_at(1)),
            ),
            artefacts=base.artefacts,
        )

        base_hash = inbox_activity_block(base, config).hash_part()
        assert inbox_activity_block(with_rating, config).hash_part() != base_hash
        assert inbox_activity_block(with_open, config).hash_part() == base_hash
