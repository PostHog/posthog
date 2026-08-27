from dataclasses import dataclass, field
from typing import Any

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import truncate_for_temporal_payload

BODY_EXCERPT_MAX_CHARS = 1500

CONFLICT_KEY = "merge-conflict"


def _excerpt(body: str | None) -> str:
    return truncate_for_temporal_payload((body or "").strip(), BODY_EXCERPT_MAX_CHARS)


@dataclass(frozen=True)
class FailingCheck:
    key: str
    details_url: str | None = None


@dataclass(frozen=True)
class ReviewThreadItem:
    id: str
    last_comment_id: str
    path: str | None = None
    author: str | None = None
    author_association: str | None = None
    body_excerpt: str = ""
    url: str | None = None


@dataclass(frozen=True)
class CommentItem:
    id: str
    author: str | None = None
    author_association: str | None = None
    body_excerpt: str = ""
    url: str | None = None


@dataclass(frozen=True)
class PRSnapshot:
    pr_url: str
    pr_state: str
    head_sha: str
    has_conflict: bool = False
    author_login: str | None = None
    failing_checks: list[FailingCheck] = field(default_factory=list)
    unresolved_threads: list[ReviewThreadItem] = field(default_factory=list)
    comments: list[CommentItem] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.pr_state in ("merged", "closed")

    @classmethod
    def from_raw(cls, raw: dict[str, Any], pr_url: str) -> "PRSnapshot":
        return cls(
            pr_url=raw.get("url") or pr_url,
            pr_state=raw.get("state") or "unknown",
            head_sha=raw.get("head_sha") or "",
            has_conflict=bool(raw.get("has_conflict")),
            author_login=raw.get("author_login"),
            failing_checks=[
                FailingCheck(key=check["key"], details_url=check.get("details_url"))
                for check in raw.get("failing_checks") or []
            ],
            unresolved_threads=[
                ReviewThreadItem(
                    id=thread["id"],
                    last_comment_id=thread.get("last_comment_id") or "",
                    path=thread.get("path"),
                    author=thread.get("author"),
                    author_association=thread.get("author_association"),
                    body_excerpt=_excerpt(thread.get("body")),
                    url=thread.get("url"),
                )
                for thread in raw.get("unresolved_threads") or []
                if thread.get("id")
            ],
            comments=[
                CommentItem(
                    id=comment["id"],
                    author=comment.get("author"),
                    author_association=comment.get("author_association"),
                    body_excerpt=_excerpt(comment.get("body")),
                    url=comment.get("url"),
                )
                for comment in raw.get("comments") or []
                if comment.get("id")
            ],
        )


@dataclass(frozen=True)
class AttentionSet:
    failing_checks: list[FailingCheck] = field(default_factory=list)
    threads: list[ReviewThreadItem] = field(default_factory=list)
    comments: list[CommentItem] = field(default_factory=list)
    conflict: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.failing_checks or self.threads or self.comments or self.conflict)

    def capped(self, max_threads: int, max_comments: int) -> "AttentionSet":
        """The newest threads and comments the wake prompt actually renders. Recording only
        these keeps the journal from marking never-shown feedback as handled — the omitted
        items stay unrecorded and resurface on a later tick."""
        return AttentionSet(
            failing_checks=self.failing_checks,
            threads=self.threads[-max_threads:],
            comments=self.comments[-max_comments:],
            conflict=self.conflict,
        )


@frozen
class BabysitJournal:
    threads: dict[str, str] = field(default_factory=dict)
    comment_ids: list[str] = field(default_factory=list)
    head_sha: str = ""
    head_keys: list[str] = field(default_factory=list)

    def attention(self, snapshot: PRSnapshot) -> AttentionSet:
        same_head = self.head_sha == snapshot.head_sha
        return AttentionSet(
            failing_checks=[
                check for check in snapshot.failing_checks if not (same_head and check.key in self.head_keys)
            ],
            threads=[
                thread
                for thread in snapshot.unresolved_threads
                # nosemgrep: openai-non-hipaa-assistants-threads — review-thread journal dict, not an OpenAI client
                if thread.author != snapshot.author_login and self.threads.get(thread.id) != thread.last_comment_id
            ],
            comments=[comment for comment in snapshot.comments if comment.id not in self.comment_ids],
            conflict=snapshot.has_conflict and not (same_head and CONFLICT_KEY in self.head_keys),
        )

    def record(self, snapshot: PRSnapshot, attention: AttentionSet) -> "BabysitJournal":
        head_keys = list(self.head_keys) if snapshot.head_sha == self.head_sha else []
        for check in attention.failing_checks:
            if check.key not in head_keys:
                head_keys.append(check.key)
        if attention.conflict and CONFLICT_KEY not in head_keys:
            head_keys.append(CONFLICT_KEY)
        return BabysitJournal(
            threads={**self.threads, **{thread.id: thread.last_comment_id for thread in attention.threads}},
            comment_ids=self.comment_ids
            + [comment.id for comment in attention.comments if comment.id not in self.comment_ids],
            head_sha=snapshot.head_sha,
            head_keys=head_keys,
        )
