from typing import Any

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


class TestEngagementMethod:
    def test_reaction_counts_as_engagement(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 2}}
        assert engagement_method(comment=comment, review_comments=[comment]) == "comment_reaction"

    def test_reply_counts_as_engagement(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1, "user": {"login": "alice", "type": "User"}}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) == "comment_reply"

    def test_bot_reply_is_not_engagement(self):
        # `reacted` means a human engaged; another review app replying in the thread must not settle
        # the finding and skip the addressing judge.
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        bot_reply: dict[str, Any] = {
            "id": 2,
            "in_reply_to_id": 1,
            "user": {"login": "greptile-apps[bot]", "type": "Bot"},
        }
        assert engagement_method(comment=comment, review_comments=[comment, bot_reply]) is None

    def test_reaction_wins_over_reply(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 1}}
        reply: dict[str, Any] = {"id": 2, "in_reply_to_id": 1}
        assert engagement_method(comment=comment, review_comments=[comment, reply]) == "comment_reaction"

    def test_no_reaction_no_reply_is_none(self):
        comment: dict[str, Any] = {"id": 1, "reactions": {"total_count": 0}}
        assert engagement_method(comment=comment, review_comments=[comment]) is None
