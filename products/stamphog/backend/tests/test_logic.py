import json
from collections.abc import Callable

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from products.stamphog.backend.logic.digest import DigestPRSummary, DigestSummary
from products.stamphog.backend.logic.digest_config import load_repo_digest_config
from products.stamphog.backend.logic.github_client import StamphogGitHubClient, StamphogGitHubError, _build_app_jwt
from products.stamphog.backend.logic.reviewer import build_reviewer_invocation, parse_reviewer_output
from products.stamphog.backend.logic.slack_digest import _build_blocks, _build_fallback_text
from products.stamphog.backend.models import StamphogRepoConfig
from products.stamphog.backend.temporal import activities as activities_module
from products.stamphog.backend.temporal.registry import ACTIVITIES
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import _generate_app_private_key

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
    def test_reviews_and_review_threads_are_threaded_into_the_context(self) -> None:
        # The hosted reviewer must receive prior PR reviews so the engine's prerequisite gate can block
        # on an active CHANGES_REQUESTED, and inline review threads so a maintainer's unresolved "do not
        # merge" reaches the prompt. If either were dropped from the context the reviewer would run
        # partly blind and could approve over a block it never saw.
        reviews = [{"user": {"login": "maintainer"}, "state": "CHANGES_REQUESTED"}]
        review_threads = [
            {"is_resolved": False, "is_outdated": False, "path": "a.py", "comments": [{"author": "m", "body": "hold"}]}
        ]
        invocation = build_reviewer_invocation(
            pr={"number": 1},
            files=[],
            reviews=reviews,
            discussion=[],
            review_threads=review_threads,
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
        assert context["review_threads"] == review_threads


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


_GH = "products.stamphog.backend.logic.github_client"


class GetPrReviewThreadsTests(SimpleTestCase):
    def _fetch(self, graphql_response: fakes.FakeResponse) -> list[dict]:
        # Stub the network boundary (github_request): the access-token mint is answered so the client's
        # _request machinery runs for real, and every /graphql call returns the scripted response.
        def fake_request(method: str, url: str, **kwargs: object) -> fakes.FakeResponse:
            if url.endswith("/access_tokens"):
                return fakes.FakeResponse(201, json_data={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
            return graphql_response

        with (
            override_settings(STAMPHOG_GITHUB_APP_ID="1", STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key()),
            patch(f"{_GH}.github_request", fake_request),
            patch(f"{_GH}.remember_observed_core_limit", lambda *a, **k: None),
            patch(f"{_GH}.raise_if_github_rate_limited", lambda *a, **k: None),
        ):
            return StamphogGitHubClient("123").get_pr_review_threads("acme/widgets", 5)

    def _threads_page(self, nodes: list[dict], *, has_next: bool) -> fakes.FakeResponse:
        payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"pageInfo": {"hasNextPage": has_next, "endCursor": "c"}, "nodes": nodes}
                    }
                }
            }
        }
        return fakes.FakeResponse(200, json_data=payload)

    def test_parses_lean_shape_and_trims_body(self) -> None:
        # The lean shape must carry the author identity triple — the engine's author-trust gate needs
        # it, or an untrusted external commenter could plant a fake maintainer hold in the prompt.
        node = fakes.review_thread_node(
            path="src/util.py",
            comments=[("maintainer", "x" * 5000)],
            is_resolved=True,
            is_outdated=False,
            line=42,
            author_association="MEMBER",
            author_typename="User",
        )
        threads = self._fetch(self._threads_page([node], has_next=False))
        assert threads == [
            {
                "is_resolved": True,
                "is_outdated": False,
                "path": "src/util.py",
                "line": 42,
                "comments": [
                    {
                        "author": "maintainer",
                        "author_association": "MEMBER",
                        "author_is_bot": False,
                        "body": "x" * 4000,
                    }
                ],
            }
        ]

    @parameterized.expand(
        [
            ("graphql_errors", fakes.FakeResponse(200, json_data={"errors": [{"message": "no access"}]})),
            ("http_failure", fakes.FakeResponse(500, text="boom")),
        ]
    )
    def test_fails_closed(self, _name: str, response: fakes.FakeResponse) -> None:
        # A silently truncated or errored thread list reads as "no blockers" to the reviewer, the one
        # wrong answer here — every failure mode must raise, exactly like get_pr_discussion.
        with pytest.raises(StamphogGitHubError):
            self._fetch(response)

    def test_comment_page_overflow_fails_closed(self) -> None:
        # A thread with more comments than one fetch window would silently lose its tail — and a
        # maintainer's hold could be comment 51. Must raise, matching the Action's escalation.
        node = fakes.review_thread_node(
            path="src/util.py", comments=[("maintainer", "hold")], comments_have_next_page=True
        )
        with pytest.raises(StamphogGitHubError):
            self._fetch(self._threads_page([node], has_next=False))

    def test_page_cap_fails_closed(self) -> None:
        # A PR whose threads never stop paginating must raise rather than review a truncated list.
        with pytest.raises(StamphogGitHubError):
            self._fetch(self._threads_page([], has_next=True))


class PrReactionFailOpenTests(SimpleTestCase):
    """add_pr_reaction / remove_pr_reaction are deliberately the one fail-open pair on this client
    (see their docstrings): a cosmetic "review in flight" 👀 must never fail or retry the calling
    review activity, unlike every other read/write on ``StamphogGitHubClient``."""

    def _call(
        self,
        transport_response_or_error: fakes.FakeResponse | Exception,
        call: Callable[[StamphogGitHubClient], object],
    ) -> object:
        def fake_request(method: str, url: str, **kwargs: object) -> fakes.FakeResponse:
            if url.endswith("/access_tokens"):
                return fakes.FakeResponse(201, json_data={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
            if isinstance(transport_response_or_error, Exception):
                raise transport_response_or_error
            return transport_response_or_error

        with (
            override_settings(STAMPHOG_GITHUB_APP_ID="1", STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key()),
            patch(f"{_GH}.github_request", fake_request),
            patch(f"{_GH}.remember_observed_core_limit", lambda *a, **k: None),
            patch(f"{_GH}.raise_if_github_rate_limited", lambda *a, **k: None),
        ):
            return call(StamphogGitHubClient("123"))

    @parameterized.expand(
        [
            ("http_error", fakes.FakeResponse(500, text="boom")),
            ("non_json_body", fakes.FakeResponse(201, text="not json")),
            ("transport_exception", RuntimeError("network blew up")),
        ]
    )
    def test_add_pr_reaction_fails_open(self, _name: str, failure: fakes.FakeResponse | Exception) -> None:
        result = self._call(failure, lambda c: c.add_pr_reaction("acme/widgets", 5))
        assert result is None

    @parameterized.expand(
        [
            ("http_error", fakes.FakeResponse(500, text="boom")),
            ("transport_exception", RuntimeError("network blew up")),
        ]
    )
    def test_remove_pr_reaction_fails_open(self, _name: str, failure: fakes.FakeResponse | Exception) -> None:
        # Must not raise — a failed removal is cosmetic cleanup, never worth retrying the activity.
        self._call(failure, lambda c: c.remove_pr_reaction("acme/widgets", 5, 999))

    def test_remove_pr_reaction_404_is_a_benign_noop(self) -> None:
        self._call(fakes.FakeResponse(404, text="not found"), lambda c: c.remove_pr_reaction("acme/widgets", 5, 999))

    def test_add_pr_reaction_200_returns_the_existing_id_not_a_new_one(self) -> None:
        # GitHub's own idempotency: reacting again with the same identity+content returns 200 with the
        # EXISTING reaction rather than 201 with a new one — the client must surface that id either way.
        response = fakes.FakeResponse(200, json_data={"id": 555, "content": "eyes"})
        result = self._call(response, lambda c: c.add_pr_reaction("acme/widgets", 5))
        assert result == 555


class BuildAppJwtIssuerTests(SimpleTestCase):
    @parameterized.expand(
        [
            ("client_id_preferred_over_app_id", "acme-client", "999", "acme-client"),
            ("app_id_fallback_when_client_id_unset", "", "999", "999"),
        ]
    )
    def test_issuer_prefers_client_id_falling_back_to_app_id(
        self, _name: str, client_id: str, app_id: str, expected_issuer: str
    ) -> None:
        with override_settings(
            STAMPHOG_GITHUB_APP_CLIENT_ID=client_id,
            STAMPHOG_GITHUB_APP_ID=app_id,
            STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key(),
        ):
            token = _build_app_jwt()
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["iss"] == expected_issuer

    def test_raises_when_neither_client_id_nor_app_id_is_configured(self) -> None:
        with override_settings(
            STAMPHOG_GITHUB_APP_CLIENT_ID="",
            STAMPHOG_GITHUB_APP_ID="",
            STAMPHOG_GITHUB_APP_PRIVATE_KEY=_generate_app_private_key(),
        ):
            with pytest.raises(StamphogGitHubError):
                _build_app_jwt()


class TemporalRegistryTests(SimpleTestCase):
    def test_every_defined_activity_is_registered_with_the_worker(self) -> None:
        # A new @activity.defn that isn't added to ACTIVITIES fails only at runtime, when the worker
        # rejects the workflow's schedule request — this has already almost shipped once.
        defined = {
            name for name, obj in vars(activities_module).items() if hasattr(obj, "__temporal_activity_definition")
        }
        registered = {fn.__name__ for fn in ACTIVITIES}
        assert defined == registered
