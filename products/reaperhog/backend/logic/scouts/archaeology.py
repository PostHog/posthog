from datetime import datetime

from products.reaperhog.backend.facade.enums import NAMED_SCOPES, SCOPE_ALL, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.constants import (
    ALL_SCOPE_ROOTS,
    DIRECTORY_HACKATHON_DAYS,
    DIRECTORY_ORPHAN_DAYS,
    DIRECTORY_STALE_DAYS,
    HACKATHON_SUBJECT,
)
from products.reaperhog.backend.logic.repo import CommitStamp
from products.reaperhog.backend.logic.scouts.base import ScoutContext, days_between


class ArchaeologyScout:
    name = ScoutName.ARCHAEOLOGY

    def applies_to(self, scope: str) -> bool:
        return scope == SCOPE_ALL or scope not in NAMED_SCOPES

    def run(self, context: ScoutContext) -> list[Hit]:
        bases = list(ALL_SCOPE_ROOTS) if context.scope == SCOPE_ALL else [context.scope_path or ""]
        hits: list[Hit] = []
        for base in bases:
            for name in context.repo.list_directories(base):
                path = f"{base}/{name}" if base else name
                stamp = context.repo.last_real_commit(path)
                if stamp is None:
                    continue
                hit = classify_directory(path, stamp, context.now, context.author_left(stamp.author_email))
                if hit is None:
                    continue
                hits.append(hit.model_copy(update={"line_count": context.repo.tracked_line_count(path)}))
        return hits


def classify_directory(path: str, stamp: CommitStamp, now: datetime, author_left: bool | None) -> Hit | None:
    days = days_between(now, stamp.committed_at)
    reasons: list[str] = []
    if days >= DIRECTORY_STALE_DAYS:
        reasons.append(f"no real commit in {days} days")
    if author_left and days >= DIRECTORY_ORPHAN_DAYS:
        reasons.append(f"last committer is no longer in the org ({days} days ago)")
    if HACKATHON_SUBJECT.search(stamp.subject) and days >= DIRECTORY_HACKATHON_DAYS:
        reasons.append(f"last real commit reads like a hackathon or spike ({days} days ago)")
    if not reasons:
        return None
    return Hit(
        scout=ScoutName.ARCHAEOLOGY,
        root_kind=RootKind.DIRECTORY,
        root=path,
        files=[path],
        summary="; ".join(reasons).capitalize(),
        evidence={
            "last_commit_sha": stamp.sha,
            "last_commit_at": stamp.committed_at.isoformat(),
            "last_commit_subject": stamp.subject,
            "last_commit_author": stamp.author_email,
            "author_left": author_left,
            "days_since_commit": days,
        },
    )
