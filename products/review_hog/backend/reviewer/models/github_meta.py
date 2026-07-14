import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PRMetadata(BaseModel):
    number: int
    title: str
    body: str = ""
    state: str
    draft: bool
    created_at: str
    updated_at: str
    author: str
    author_association: str = "NONE"
    base_branch: str
    head_branch: str
    # True when the PR head lives in a different repo than the base (a fork). Forks carry
    # attacker-influenced head refs and their branch isn't on the base origin, so the review refuses
    # them. Defaults false so a pre-field cached pr_meta.json still parses (treated as non-fork).
    is_fork: bool = False
    # The PR head commit SHA — the exact code a review judges. Anchors the per-turn diff snapshot
    # and the report's head_sha watermark. Optional so a pre-snapshot cached pr_meta.json still parses.
    head_sha: str | None = None
    mergeable_state: str | None = None
    requested_reviewers: list[str] = Field(default_factory=list)
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    commits: int
    additions: int
    deletions: int
    changed_files: int


class PRComment(BaseModel):
    # GitHub review-comment id — feeds the report's last_seen_comment_id watermark so a later turn
    # knows which comments are new. Optional so a pre-watermark cached pr_comments.jsonl still parses.
    id: int | None = None
    path: str
    line: int | None = None
    start_line: int | None = None
    body: str
    diff_hunk: str
    user: str
    created_at: str


class PRFileUpdate(BaseModel):
    type: str  # "addition", "deletion", or "context"
    old_start_line: int | None = None
    old_end_line: int | None = None
    new_start_line: int | None = None
    new_end_line: int | None = None
    code: str


class PRFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    changes: list[PRFileUpdate] = Field(default_factory=list)
