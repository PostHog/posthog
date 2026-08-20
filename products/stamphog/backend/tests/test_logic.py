import json
from collections.abc import Callable

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from products.stamphog.backend.facade.enums import AudienceReason
from products.stamphog.backend.logic.approval_retention import approved_diff_unchanged
from products.stamphog.backend.logic.audiences import resolve_audiences
from products.stamphog.backend.logic.digest import DigestPRSummary, DigestSummary
from products.stamphog.backend.logic.digest_config import RepoDigestConfig, load_repo_digest_config
from products.stamphog.backend.logic.github_client import (
    MAX_COMPARE_DIFF_BYTES,
    StamphogGitHubClient,
    StamphogGitHubError,
    _build_app_jwt,
)
from products.stamphog.backend.logic.reviewer import build_reviewer_invocation, parse_reviewer_output
from products.stamphog.backend.logic.slack_digest import _build_blocks, _build_fallback_text
from products.stamphog.backend.models import StamphogRepoConfig
from products.stamphog.backend.temporal import activities as activities_module
from products.stamphog.backend.temporal.registry import ACTIVITIES
from products.stamphog.backend.tests import fakes
from products.stamphog.backend.tests.conftest import _generate_app_private_key

# The gate/policy engine lives in packages/pr-approval-agent, and its own suite covers it
# (test_gates.py, test_policy.py). It runs inside the sandbox rather than server-side, so there is
# no ported copy to test here. Only the defensive parsing of the engine's stdout contract remains
# server-side.


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
            author_team_slugs=[],
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
            pr_number=7,
            title=title,
            url="https://github.com/o/r/pull/7",
            author_login=author,
            summary=body,
            repository="o/r",
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

    def test_pr_lines_name_the_repo_only_when_the_digest_spans_repos(self) -> None:
        # A team audience collects merges from every repo it owns code in, and PR numbers repeat
        # across repos — two "#412" lines that differ only by link target are unreadable. The far
        # more common single-repo digest must not pay a constant repo prefix on every line.
        def _pr(repository: str, number: int) -> DigestPRSummary:
            return DigestPRSummary(
                pr_number=number,
                title="Ship it",
                url=f"https://github.com/{repository}/pull/{number}",
                author_login="dev",
                summary="did a thing",
                repository=repository,
            )

        one_repo = DigestSummary(intro="", prs=[_pr("acme/widgets", 412), _pr("acme/widgets", 413)])
        two_repos = DigestSummary(intro="", prs=[_pr("acme/widgets", 412), _pr("acme/charts", 412)])

        assert "#412 Ship it" in _build_fallback_text(one_repo)
        assert "acme/widgets#412" not in _build_fallback_text(one_repo)
        sections = [b["text"]["text"] for b in _build_blocks(one_repo) if b.get("type") == "section"]
        assert any("|#412 Ship it>" in text for text in sections)

        assert "acme/widgets#412" in _build_fallback_text(two_repos)
        assert "acme/charts#412" in _build_fallback_text(two_repos)
        sections = [b["text"]["text"] for b in _build_blocks(two_repos) if b.get("type") == "section"]
        assert any("|acme/charts#412 Ship it>" in text for text in sections)

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
    def _fetch(self, *graphql_responses: fakes.FakeResponse) -> list[dict]:
        # Stub the network boundary (github_request): the access-token mint is answered so the client's
        # _request machinery runs for real, and /graphql calls consume the scripted responses in order
        # (the last one repeats, so single-response tests behave as before).
        remaining = list(graphql_responses)

        def fake_request(method: str, url: str, **kwargs: object) -> fakes.FakeResponse:
            if url.endswith("/access_tokens"):
                return fakes.FakeResponse(201, json_data={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

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

    def _thread_comments_page(self, comments: list[tuple[str, str]], *, has_next: bool) -> fakes.FakeResponse:
        payload = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": "cc2"},
                        "nodes": [
                            {
                                "author": {"login": author, "__typename": "User"},
                                "authorAssociation": "MEMBER",
                                "body": body,
                            }
                            for author, body in comments
                        ],
                    }
                }
            }
        }
        return fakes.FakeResponse(200, json_data=payload)

    def test_comment_page_overflow_pages_the_tail(self) -> None:
        # A >window thread must not fail the review (one chatty thread would make the PR permanently
        # unreviewable) NOR silently drop its tail (comment 51 could be a maintainer's hold): the tail
        # pages via the per-thread query and lands appended, in order.
        node = fakes.review_thread_node(
            path="src/util.py", comments=[("maintainer", "hold")], comments_have_next_page=True
        )
        threads = self._fetch(
            self._threads_page([node], has_next=False),
            self._thread_comments_page([("maintainer", "still holding")], has_next=False),
        )
        assert [c["body"] for c in threads[0]["comments"]] == ["hold", "still holding"]

    def test_comment_tail_page_cap_fails_closed(self) -> None:
        # A thread whose comment tail never stops paginating (pathological) must raise rather than
        # return a thread the reviewer would read as complete.
        node = fakes.review_thread_node(
            path="src/util.py", comments=[("maintainer", "hold")], comments_have_next_page=True
        )
        with pytest.raises(StamphogGitHubError):
            self._fetch(
                self._threads_page([node], has_next=False),
                self._thread_comments_page([("maintainer", "more")], has_next=True),
            )

    def test_page_cap_fails_closed(self) -> None:
        # A PR whose threads never stop paginating must raise rather than review a truncated list.
        with pytest.raises(StamphogGitHubError):
            self._fetch(self._threads_page([], has_next=True))


# add_pr_reaction / remove_pr_reaction are deliberately the one fail-open pair on the client
# (see their docstrings): a cosmetic "review in flight" 👀 must never fail or retry the calling
# review activity, unlike every other read/write on StamphogGitHubClient.
class PrReactionFailOpenTests(SimpleTestCase):
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


class ResolveAudiencesTests(SimpleTestCase):
    @staticmethod
    def _gate_result(teams: object) -> dict:
        return {"classification": {"ownership": {"teams": teams}}}

    @parameterized.expand(
        [
            (
                "owning_teams_join_the_author",
                ["@PostHog/team-replay", "@PostHog/team-surveys"],
                [
                    ("team-devex", AudienceReason.AUTHORED),
                    ("team-replay", AudienceReason.OWNED),
                    ("team-surveys", AudienceReason.OWNED),
                ],
            ),
            (
                "author_owning_its_own_code_stays_one_audience",
                ["@PostHog/team-devex", "@PostHog/team-replay"],
                [("team-devex", AudienceReason.AUTHORED), ("team-replay", AudienceReason.OWNED)],
            ),
            ("individual_owners_are_not_audiences", ["@someone"], [("team-devex", AudienceReason.AUTHORED)]),
            (
                "a_crafted_slug_cannot_claim_the_repo_namespace",
                ["@PostHog/repo:PostHog/posthog", "@PostHog/team with spaces"],
                [("team-devex", AudienceReason.AUTHORED)],
            ),
            ("missing_ownership_section", None, [("team-devex", AudienceReason.AUTHORED)]),
            ("malformed_ownership_section", "team-replay", [("team-devex", AudienceReason.AUTHORED)]),
        ]
    )
    def test_owner_teams_become_audiences(self, _name: str, teams: object, expected: list) -> None:
        # Owner audiences are what carry "this changed in your area", and they are read back out of a
        # blob the sandbox wrote, so a shape the engine never promised must degrade to author-only
        # rather than dropping the merge. The author winning a collision is what keeps a team that
        # wrote its own code out of its own "changed in your area" list. Ownership comes from the
        # PR-head owners.yaml, so a slug is attacker-controlled: one shaped like "repo:owner/name"
        # would otherwise reach the channel path that auto-enables and skips the shared-channel guard.
        repo_config = StamphogRepoConfig(repository="PostHog/posthog", installation_id="1")
        with (
            patch("products.stamphog.backend.logic.audiences.load_repo_digest_config", return_value=None),
            patch(
                "products.stamphog.backend.logic.audiences._author_team_audience_key",
                return_value="team-devex",
            ),
        ):
            audiences = resolve_audiences(repo_config, {}, self._gate_result(teams))
        assert [(a.key, a.reason) for a in audiences] == expected

    def test_repo_declared_channel_still_collects_owner_audiences(self) -> None:
        # A repo that pins all its merges to one channel still has owning teams, and they should
        # hear about their area — the declared channel replaces the author cascade, not the fan-out.
        repo_config = StamphogRepoConfig(repository="PostHog/posthog", installation_id="1")
        with patch(
            "products.stamphog.backend.logic.audiences.load_repo_digest_config",
            return_value=RepoDigestConfig(channel="eng-merges"),
        ):
            audiences = resolve_audiences(repo_config, {}, self._gate_result(["@PostHog/team-replay"]))
        assert [(a.key, a.reason) for a in audiences] == [
            ("repo:PostHog/posthog", AudienceReason.REPO_DECLARED),
            ("team-replay", AudienceReason.OWNED),
        ]


class OwnedFileCountTests(SimpleTestCase):
    def test_true_owned_count_survives_the_capped_sample(self) -> None:
        # The sample is capped and the count is not. If the prompt reported the sample size, a team
        # owning most of a large change would look grazed by it and get filtered out of its own digest.
        repo_config = StamphogRepoConfig(repository="PostHog/posthog", installation_id="1")
        gate_result = {
            "classification": {
                "ownership": {
                    "teams": ["@PostHog/team-replay"],
                    "team_files": {"@PostHog/team-replay": [f"a{i}.py" for i in range(10)]},
                    "team_file_counts": {"@PostHog/team-replay": 200},
                }
            }
        }
        with (
            patch("products.stamphog.backend.logic.audiences.load_repo_digest_config", return_value=None),
            patch("products.stamphog.backend.logic.audiences._author_team_audience_key", return_value="team-devex"),
        ):
            owned = next(a for a in resolve_audiences(repo_config, {}, gate_result) if a.key == "team-replay")
        assert len(owned.owned_files) == 10
        assert owned.owned_file_count == 200


_DIFF = """diff --git a/posthog/api/thing.py b/posthog/api/thing.py
index aaa..bbb 100644
--- a/posthog/api/thing.py
+++ b/posthog/api/thing.py
@@ -1,2 +1,3 @@
 keep
+added
"""

_DIFF_MODE_FLIPPED = _DIFF.replace("index aaa..bbb 100644", "old mode 100644\nnew mode 100755\nindex aaa..bbb 100755")


class CompareDiffSizeTests(SimpleTestCase):
    @staticmethod
    def _streamed(body: bytes) -> MagicMock:
        response = MagicMock(status_code=200)
        response.iter_content.return_value = iter([body[i : i + 1024] for i in range(0, len(body), 1024)])
        return response

    def test_diff_under_the_ceiling_is_returned(self) -> None:
        response = self._streamed(b"diff --git a/x b/x\n")

        with patch.object(StamphogGitHubClient, "_request", return_value=response):
            assert StamphogGitHubClient("42").compare_diff("o/r", "base", "head") == "diff --git a/x b/x\n"

    def test_oversized_diff_raises_instead_of_buffering(self) -> None:
        # GitHub answers 200 for a diff of any size, and a range that spans thousands of files
        # returns hundreds of megabytes. This ceiling refuses the cost of reading that into a
        # worker.
        response = self._streamed(b"x" * (MAX_COMPARE_DIFF_BYTES + 4096))

        with patch.object(StamphogGitHubClient, "_request", return_value=response):
            with pytest.raises(StamphogGitHubError):
                StamphogGitHubClient("42").compare_diff("o/r", "base", "head")


class ApprovalRetentionTests(SimpleTestCase):
    def test_unchanged_diff_retains_across_a_base_merge(self) -> None:
        # A merge of the base branch into a PR is the most common push on a long-lived PR. It does
        # not change the PR's own diff, so there is nothing new to review, and a dismissal would
        # drop the PR out of merge readiness for no reason.
        assert approved_diff_unchanged(_DIFF, _DIFF) is True

    def test_content_change_dismisses(self) -> None:
        assert approved_diff_unchanged(_DIFF, _DIFF.replace("+added", "+something else")) is False

    def test_mode_flip_dismisses(self) -> None:
        # A blob sha covers a file's contents and not its tree mode, so a per-file sha comparison
        # missed an executable-bit flip on a file that the PR already edits. The unified diff
        # carries the mode, and the comparison therefore uses the diff text.
        assert approved_diff_unchanged(_DIFF, _DIFF_MODE_FLIPPED) is False

    def test_binary_change_fails_closed(self) -> None:
        # git renders a binary change over an abbreviated blob id and never as content, so two
        # different binaries whose ids share that prefix produce the same line. An attacker can pad
        # one binary until its id collides, so a diff that carries this line cannot show whether the
        # content changed.
        binary = (
            "diff --git a/thing.wasm b/thing.wasm\n"
            "index aaa1234..bbb5678 100644\n"
            "Binary files a/thing.wasm and b/thing.wasm differ\n"
        )

        assert approved_diff_unchanged(binary, binary) is False
        assert approved_diff_unchanged(_DIFF + binary, _DIFF + binary) is False

    @parameterized.expand([("both_empty", "", ""), ("approved_empty", "", _DIFF), ("current_empty", _DIFF, "")])
    def test_empty_diff_fails_closed(self, _name: str, approved: str, current: str) -> None:
        # Two blanks compare equal. Retention on that evidence would treat an unreadable answer as
        # "nothing changed".
        assert approved_diff_unchanged(approved, current) is False
