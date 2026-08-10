from typing import Any

from django.test import override_settings

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.outcomes.comment_signal import engagement_method, find_finding_comment


def _finding(title: str = "Off-by-one", file: str = "f.py") -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key="r1:f.py:10:logic",
        run_index=1,
        title=title,
        file=file,
        lines=[LineRange(start=10)],
        body="loop runs one short",
        suggestion="use <=",
        priority=IssuePriority.MUST_FIX,
    )


class TestFindFindingComment:
    def test_matches_by_path_and_title_heading(self):
        # ReviewHog's comment body leads with "### {title}"; matching on that + path is how a finding
        # maps to its posted comment without a stored id, and it must survive extra body content.
        comments: list[dict[str, Any]] = [{"id": 1, "path": "f.py", "body": "### Off-by-one\n\n![badge](x)"}]
        assert find_finding_comment(finding=_finding(), review_comments=comments) == comments[0]

    def test_no_match_on_different_path(self):
        comments: list[dict[str, Any]] = [{"id": 1, "path": "other.py", "body": "### Off-by-one"}]
        assert find_finding_comment(finding=_finding(), review_comments=comments) is None

    def test_no_match_on_different_title(self):
        comments: list[dict[str, Any]] = [{"id": 1, "path": "f.py", "body": "### Something else"}]
        assert find_finding_comment(finding=_finding(), review_comments=comments) is None

    def test_no_match_when_title_is_a_prefix_of_the_heading(self):
        # "Off-by-one" must not claim the comment for "Off-by-one in pagination" — a prefix match
        # would attribute one thread's engagement to a different finding.
        comments: list[dict[str, Any]] = [{"id": 1, "path": "f.py", "body": "### Off-by-one in pagination\n\nbody"}]
        assert find_finding_comment(finding=_finding(), review_comments=comments) is None


_OUR_BOT: dict[str, Any] = {"login": "reviewhog[bot]", "type": "Bot"}
_OTHER_BOT: dict[str, Any] = {"login": "greptile-apps[bot]", "type": "Bot"}


class TestEngagementMethod:
    def test_reaction_counts_as_engagement(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 2}}
        assert engagement_method(comment=comment, review_comments=[comment]) == "comment_reaction"

    def test_reply_counts_as_engagement(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": {"login": "alice", "type": "User"}}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) == "comment_reply"

    @override_settings(REVIEWHOG_GITHUB_BOT_LOGIN=_OUR_BOT["login"])
    def test_our_own_reply_is_never_engagement(self):
        # ReviewHog posts the finding comment itself, so counting its own follow-up would let the
        # feature grade its own homework. A fix it lands is captured as a commit the judge rules on.
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": _OUR_BOT}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) is None

    @override_settings(REVIEWHOG_GITHUB_BOT_LOGIN=_OUR_BOT["login"])
    def test_another_agents_reply_is_engagement_tagged_as_agent(self):
        # A reviewer's own bot answering on their behalf is a real response to the finding. Dropping
        # it under-reports engagement, so the actor rides in the method instead of being filtered out.
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": _OTHER_BOT}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) == "comment_reply_agent"

    @override_settings(REVIEWHOG_GITHUB_BOT_LOGIN=_OUR_BOT["login"])
    def test_human_reply_wins_over_an_agent_reply(self):
        # Both are engagement, but "a human responded" has to stay answerable once agents do more of
        # the replying, so the human actor takes the thread.
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        agent: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": _OTHER_BOT}
        human: dict[str, Any] = {"id": 3, "in_reply_to_id": 1, "user": {"login": "alice", "type": "User"}}
        assert engagement_method(comment=comment, review_comments=[comment, agent, human]) == "comment_reply"

    def test_agent_replies_are_ignored_when_our_bot_login_is_unconfigured(self):
        # `is_app_bot_author` fails open to "any bot" without REVIEWHOG_GITHUB_BOT_LOGIN, so a
        # stranger's bot is never credited as engagement on a deployment that cannot tell it from
        # ours — the signal degrades to the old ignore-every-bot behaviour rather than misattributing.
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": _OTHER_BOT}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) is None

    def test_reaction_wins_over_reply(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 1}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) == "comment_reaction"

    def test_no_reaction_no_reply_is_none(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        assert engagement_method(comment=comment, review_comments=[comment]) is None
