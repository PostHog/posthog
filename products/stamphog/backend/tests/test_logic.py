from django.test import SimpleTestCase

from products.stamphog.backend.logic.reviewer import parse_reviewer_output

# The gate/policy engine now lives in tools/pr-approval-agent and is covered by its
# own suite (test_gates.py, test_policy.py); it runs inside the sandbox rather than
# server-side, so there is no ported copy to test here. What remains server-side is
# the defensive parsing of the engine's stdout contract.


class ParseReviewerOutputTests(SimpleTestCase):
    def test_parses_rich_final_verdict_contract(self) -> None:
        raw = (
            '{"stamphog_version": "2.0.0b1", "final_verdict": "APPROVED", '
            '"gates": [{"gate": "size", "passed": true, "message": "ok"}], '
            '"reviewer": {"verdict": "APPROVE", "reasoning": "Looks fine.", "issues": []}, '
            '"review_body": "Looks fine."}'
        )

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "approved"
        assert verdict.reasoning == "Looks fine."
        assert verdict.gate_blocked is False
        assert verdict.review_body == "Looks fine."
        assert verdict.stamphog_version == "2.0.0b1"

    def test_failed_gate_marks_gate_blocked(self) -> None:
        raw = (
            '{"final_verdict": "REFUSED", '
            '"gates": [{"gate": "deny-list", "passed": false, "message": "matches: secrets"}], '
            '"reviewer": {"verdict": "REFUSE", "reasoning": "Touches secrets.", "issues": ["secrets"]}}'
        )

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "refused"
        assert verdict.gate_blocked is True

    def test_parses_legacy_verdict_line(self) -> None:
        raw = '{"verdict": "APPROVE", "reasoning": "Looks fine.", "issues": []}'

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "approved"
        assert verdict.showstoppers == []

    def test_scans_past_noisy_log_lines_for_the_last_verdict(self) -> None:
        raw = "\n".join(
            [
                "some uv log line",
                '{"not": "a verdict"}',
                '{"verdict": "REFUSE", "reasoning": "Bad idea.", "issues": ["no tests"]}',
                "trailing sdk teardown noise",
            ]
        )

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "refused"
        assert verdict.showstoppers == ["no tests"]

    def test_garbage_output_falls_back_to_escalate(self) -> None:
        verdict = parse_reviewer_output("not json at all\nstill not json")

        assert verdict.verdict == "escalate"
        assert verdict.showstoppers

    def test_unrecognized_verdict_string_escalates_with_note(self) -> None:
        raw = '{"verdict": "MAYBE", "reasoning": "Unsure.", "issues": []}'

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "escalate"
        assert any("MAYBE" in note for note in verdict.showstoppers)
