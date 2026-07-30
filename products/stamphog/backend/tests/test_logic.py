import json

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from products.stamphog.backend.logic.digest import DigestPRSummary, DigestSummary
from products.stamphog.backend.logic.digest_config import load_repo_digest_config
from products.stamphog.backend.logic.github_client import StamphogGitHubError
from products.stamphog.backend.logic.reviewer import build_reviewer_invocation, parse_reviewer_output
from products.stamphog.backend.logic.slack_digest import _build_blocks, _build_fallback_text
from products.stamphog.backend.models import StamphogRepoConfig
from products.stamphog.backend.temporal import activities as activities_module
from products.stamphog.backend.temporal.registry import ACTIVITIES

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


class BuildReviewerInvocationTests(SimpleTestCase):
    def test_reviews_are_threaded_into_the_context(self) -> None:
        # The hosted reviewer must receive prior PR reviews so the engine's prerequisite gate can block
        # on an active CHANGES_REQUESTED. If reviews were dropped from the context the reviewer would run
        # review-blind and could approve over a maintainer's block.
        reviews = [{"user": {"login": "maintainer"}, "state": "CHANGES_REQUESTED"}]
        invocation = build_reviewer_invocation(
            pr={"number": 1},
            files=[],
            reviews=reviews,
            discussion=[],
            check_runs=[],
            pr_reactions=[],
            author_pr_numbers=[],
            base_sha="base",
            head_sha="head",
            repo="owner/repo",
            engine_dir="/engine",
            context_path="/ctx.json",
        )
        context = json.loads(invocation.context_json)
        assert context["reviews"] == reviews


class SlackDigestEscapingTests(SimpleTestCase):
    def _summary(self, *, title: str, author: str, body: str, intro: str = "") -> DigestSummary:
        pr = DigestPRSummary(
            pr_number=7, title=title, url="https://github.com/o/r/pull/7", author_login=author, summary=body
        )
        return DigestSummary(intro=intro, prs=[pr])

    def test_mention_tokens_in_pr_fields_are_defanged(self) -> None:
        # A merged PR's title/summary/author are attacker-controlled; a raw `<!channel>` would ping the
        # whole digest channel. Escaping must neutralize the mention while keeping the trusted PR link.
        blocks = _build_blocks(self._summary(title="<!channel> ship", author="<!here>", body="see <x|y>"))
        section = next(b for b in blocks if b.get("type") == "section" and "pull/7" in b["text"]["text"])
        text = section["text"]["text"]
        assert "<!channel>" not in text
        assert "<!here>" not in text
        assert "&lt;!channel&gt;" in text
        assert "<https://github.com/o/r/pull/7|" in text

    def test_fallback_text_defangs_mentions(self) -> None:
        text = _build_fallback_text(self._summary(title="<!channel>", author="a", body="b", intro="<!everyone>"))
        assert "<!channel>" not in text
        assert "<!everyone>" not in text

    def test_section_text_is_capped_below_slack_limit(self) -> None:
        # Slack rejects sections whose mrkdwn text exceeds 3000 chars, and a rejected post unlinks the
        # claimed PRs — an unbounded LLM intro or per-PR summary would make every daily retry fail the
        # same way forever. The PR link must survive the clip (it sits at the front of the section).
        blocks = _build_blocks(self._summary(title="t", author="a", body="x" * 10_000, intro="i" * 10_000))
        sections = [b for b in blocks if b.get("type") == "section"]
        assert sections and all(len(b["text"]["text"]) <= 3000 for b in sections)
        pr_section = next(b for b in sections if "pull/7" in b["text"]["text"])
        assert "<https://github.com/o/r/pull/7|" in pr_section["text"]["text"]


class DigestConfigFetchTests(SimpleTestCase):
    def test_transient_fetch_errors_propagate(self) -> None:
        # The resolved audience is persisted on the merged PR and never recomputed, so swallowing a
        # transient GitHub failure here would permanently route the merge to the author/team fallback
        # instead of the declared channel. Only confirmed absence (404 -> None inside the client) may
        # yield None; a blip must raise so the merge-record Celery task retries the delivery.
        config = StamphogRepoConfig(repository="o/r", installation_id="1")
        with patch("products.stamphog.backend.logic.digest_config.StamphogGitHubClient") as client_cls:
            client_cls.return_value.get_default_branch_file.side_effect = StamphogGitHubError("503 from GitHub")
            with pytest.raises(StamphogGitHubError):
                load_repo_digest_config(config)


class TemporalRegistryTests(SimpleTestCase):
    def test_every_defined_activity_is_registered_with_the_worker(self) -> None:
        # A new @activity.defn that isn't added to ACTIVITIES fails only at runtime, when the worker
        # rejects the workflow's schedule request — this has already almost shipped once.
        defined = {
            name for name, obj in vars(activities_module).items() if hasattr(obj, "__temporal_activity_definition")
        }
        registered = {fn.__name__ for fn in ACTIVITIES}
        assert defined == registered
