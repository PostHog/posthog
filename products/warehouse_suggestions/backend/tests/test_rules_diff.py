from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind
from products.warehouse_suggestions.backend.logic.candidates.certify import CertifyCandidate
from products.warehouse_suggestions.backend.logic.rules import RULES
from products.warehouse_suggestions.backend.logic.rules_diff import (
    InvalidRuleOverrideError,
    KindDiff,
    diff_candidates,
    override_rules,
    results_the_job_would_keep,
)
from products.warehouse_suggestions.backend.tests.factories import busy_reads, context, team_reads, view, view_subject


class TestRulesDiff(SimpleTestCase):
    def test_a_raised_floor_reports_the_candidates_it_removes(self) -> None:
        busy, quiet = view(uuid4(), name="busy"), view(uuid4(), name="quiet")
        reads = team_reads(
            {
                view_subject(busy.id): busy_reads(human_requests=500, human_users=9),
                view_subject(quiet.id): busy_reads(human_requests=400, human_users=6),
            }
        )
        proposed = override_rules(RULES, ["certify.top_share=1", "certify.min_users=7"])
        current = override_rules(RULES, ["certify.top_share=1"])

        diff = diff_candidates(
            {
                WarehouseSuggestionKind.CERTIFY: CertifyCandidate().evaluate(
                    context(reads, views=[busy, quiet], rules=current)
                )
            },
            {
                WarehouseSuggestionKind.CERTIFY: CertifyCandidate().evaluate(
                    context(reads, views=[busy, quiet], rules=proposed)
                )
            },
        )

        assert diff[WarehouseSuggestionKind.CERTIFY] == KindDiff(added=(), removed=("quiet",), reranked=())

    def test_an_eligibility_floor_the_team_no_longer_meets_removes_every_candidate(self) -> None:
        busy = view(uuid4(), name="busy")
        reads = team_reads({view_subject(busy.id): busy_reads()})
        current, proposed = (
            context(reads, views=[busy], rules=override_rules(RULES, ["certify.top_share=1", *extra]))
            for extra in ([], ["eligibility.min_view_readers=11"])
        )

        diff = diff_candidates(
            results_the_job_would_keep(
                current, {WarehouseSuggestionKind.CERTIFY: CertifyCandidate().evaluate(current)}
            ),
            results_the_job_would_keep(
                proposed, {WarehouseSuggestionKind.CERTIFY: CertifyCandidate().evaluate(proposed)}
            ),
        )

        assert diff[WarehouseSuggestionKind.CERTIFY] == KindDiff(added=(), removed=("busy",), reranked=())

    @parameterized.expand(
        [
            ("no_section", "min_users=7"),
            ("unknown_rule", "certify.min_people=7"),
            ("not_a_number_rule", "traffic.background_kinds=temporal"),
        ]
    )
    def test_rejects_an_override_it_cannot_apply(self, _name: str, assignment: str) -> None:
        with self.assertRaises(InvalidRuleOverrideError):
            override_rules(RULES, [assignment])
