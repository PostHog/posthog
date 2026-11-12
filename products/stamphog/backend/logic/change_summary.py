"""Taking a reviewed change summary apart into the sentence about the whole change and each team's clause.

The stamphog reviewer writes ``ReviewRun.change_summary``: one sentence, plus one clause per owning team
when more than one team owns files in the change. The daily digest and the routing run list both read it
through this module, so a team sees the same clause in either place.
"""

from __future__ import annotations

import re

import structlog

from posthog.dataclasses import frozen

from .audiences import team_slug_from_handle

logger = structlog.get_logger(__name__)

# Where a reviewed summary stops describing the whole change and starts addressing one team. The
# reviewer opens each per-team clause with that team's GitHub handle, copied from the ownership
# block it was given (see packages/pr-approval-agent/reviewer.py). The handle is captured so a
# clause can be matched to the team it was written for.
#
# A clause opens a sentence, so the handle is only matched at the start of the summary or after
# sentence-ending punctuation. A scoped package name inside a sentence (`@posthog/cli:`) is prose.
_TEAM_CLAUSE_RE = re.compile(r"(?:^|(?<=[.!?])\s+)(@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+):")
# Any handle-shaped token at all, wherever it sits. One the anchored pattern did not consume is a
# clause the reviewer opened without ending the sentence before it, or a token the prompt forbids,
# and either way the text around it can no longer be trusted to belong to one team.
_ANY_HANDLE_RE = re.compile(r"@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:")


@frozen
class ReviewedSummary:
    """A reviewed summary taken apart: the sentence about the whole change, and each team's clause.

    ``clauses`` is keyed by the casefolded team slug the clause opens with. Empty for a summary
    about a merge one team owns, and for every summary an engine older than the per-team clauses
    wrote.
    """

    whole_change: str
    clauses: dict[str, str]


def split_clauses(summary_line: str) -> ReviewedSummary:
    """Split a reviewed summary on the handles its per-team clauses open with.

    ``re.split`` on a pattern with one group returns the text before the first match, then each
    captured handle followed by the text after it, so the parts alternate from index 1 onwards.

    The first clause a slug opens wins, so a handle the reviewer names again later inside another
    team's clause cannot replace that team's own clause.
    """
    parts = _TEAM_CLAUSE_RE.split(summary_line)
    clauses: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        clauses.setdefault(team_slug_from_handle(parts[i]).casefold(), parts[i + 1].strip())
    whole_change = parts[0].strip()
    # A handle left inside a part is a clause boundary the split did not see, so that part carries
    # another team's text. Discarding the whole summary costs this team the reviewed sentence and
    # leaves it the title; keeping it would post the other team's clause under this team's name.
    if _ANY_HANDLE_RE.search(whole_change) or any(_ANY_HANDLE_RE.search(clause) for clause in clauses.values()):
        logger.info("stamphog_digest_summary_unparsed")
        return ReviewedSummary(whole_change="", clauses={})
    return ReviewedSummary(whole_change=whole_change, clauses=clauses)
