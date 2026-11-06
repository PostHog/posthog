"""Preview path assignees from current ownership, an explicit roster, and local git history."""

from __future__ import annotations

import re
import sys
import json
import argparse
import subprocess
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from owners_yaml import OwnersResolver, compile_pattern
from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen

HISTORY_DAYS = 180
ACTIVE_DAYS = 90
HALF_LIFE_DAYS = 30
MAX_COMMITS = 5000
MAX_PARENT_LEVELS = 4
MAX_ROSTER_AGE = timedelta(days=7)
MECHANICAL_CHANGE = re.compile(r"^(?:style(?:\([^)]*\))?:|chore(?:\([^)]*\))?:\s*(?:format|lint|sort imports)\b)", re.I)


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    login: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    emails: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()
    excluded_paths: tuple[str, ...] = ()
    active: bool = True


class Roster(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    members: tuple[Member, ...]

    @model_validator(mode="after")
    def validate_identities(self) -> Roster:
        if self.generated_at.tzinfo is None:
            raise ValueError("Roster generated_at must include a timezone")
        logins = [member.login.lower() for member in self.members]
        emails = [email.lower() for member in self.members for email in member.emails]
        if len(set(logins)) != len(logins) or len(set(emails)) != len(emails):
            raise ValueError("Roster logins and email mappings must be unique")
        return self


@frozen
class Commit:
    sha: str
    email: str
    authored_at: datetime
    subject: str
    paths: tuple[str, ...]


@frozen
class History:
    commits: tuple[Commit, ...]
    complete: bool


@frozen
class ScopedCommit:
    scope_index: int
    commit: Commit
    paths: tuple[str, ...]


@frozen
class EvidenceIndex:
    by_login: dict[str, list[ScopedCommit]]
    unmatched_author_count: int
    unmatched_direct_author_count: int


@frozen
class CommitEvidence:
    sha: str
    authored_at: datetime
    subject: str
    paths: tuple[str, ...]
    scope: str


@frozen
class Candidate:
    login: str
    score: float
    matches_declared_ownership: bool
    active_in_scope: bool
    nearest_scope: str | None
    directory_distance: int | None
    last_authored_at: datetime | None
    evidence_shas: tuple[str, ...]
    evidence: tuple[CommitEvidence, ...]


@frozen
class RejectedCandidate:
    login: str
    reason: str
    last_authored_at: datetime | None


DecisionReason = Literal[
    "direct_owner_evidence",
    "no_declared_owner",
    "parent_only_evidence",
    "no_recent_owner_evidence",
    "ownership_conflict",
    "multiple_owner_teams",
    "tied_candidates",
    "incomplete_history",
    "stale_roster",
    "unmapped_direct_authors",
    "no_candidates",
]


@frozen
class AgentDecision:
    case: Literal["confirm_owner", "needs_investigation", "unresolved"]
    reason_codes: tuple[DecisionReason, ...]
    checks: tuple[str, ...]
    max_pull_requests: int


@frozen
class AssigneeRanking:
    schema_version: int
    path: str
    owners: tuple[str, ...]
    ownership_source: str | None
    ownership_is_inherited: bool
    scopes: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    investigation_candidates: tuple[Candidate, ...]
    excluded: tuple[RejectedCandidate, ...]
    recommended_assignee: str | None
    warnings: tuple[str, ...]
    agent_decision: AgentDecision


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, timeout=60)


def load_history(repo: Path, scope: str, now: datetime) -> History:
    raw = git(
        repo,
        "log",
        "--no-merges",
        f"--max-count={MAX_COMMITS + 1}",
        f"--since-as-filter={(now - timedelta(days=HISTORY_DAYS)).isoformat()}",
        "--format=%x1e%H%x00%aI%x00%ae%x00%s%x00",
        "--name-only",
        "-z",
        "--",
        f":(literal){scope}",
    )
    commits = []
    for record in raw.split("\x1e")[1:]:
        sha, authored_at, email, subject, paths = record.split("\0", 4)
        commits.append(
            Commit(
                sha=sha,
                email=email.lower(),
                authored_at=datetime.fromisoformat(authored_at),
                subject=subject,
                paths=tuple(path for path in paths.lstrip("\0").removeprefix("\n").split("\0") if path),
            )
        )
    complete = git(repo, "rev-parse", "--is-shallow-repository").strip() == "false" and len(commits) <= MAX_COMMITS
    return History(commits=tuple(commits[:MAX_COMMITS]), complete=complete)


def path_in_scope(path: str, scope: str) -> bool:
    return path == scope or path.startswith(f"{scope}/")


def traversal_scopes(path: str, owners: set[str], resolver: OwnersResolver) -> tuple[str, ...]:
    scopes = [path]
    parent = Path(path).parent
    while parent != Path(".") and len(scopes) <= MAX_PARENT_LEVELS:
        probe = (parent / "__assignee_scope__").as_posix()
        if owners and not owners.intersection(resolver.resolve(probe).owners or []):
            break
        if not owners and len(parent.parts) < 2:
            break
        scopes.append(parent.as_posix())
        parent = parent.parent
    return tuple(scopes)


def is_path_excluded(member: Member, path: str, *, is_directory: bool = False) -> bool:
    return any(
        compile_pattern(pattern).test(path)
        or (is_directory and compile_pattern(pattern).test(f"{path}/__assignee_scope__"))
        for pattern in member.excluded_paths
    )


def collect_evidence(
    roster: Roster, history: History, scopes: tuple[str, ...], owners: set[str], resolver: OwnersResolver, now: datetime
) -> EvidenceIndex:
    by_email = {email.lower(): member for member in roster.members for email in member.emails}
    evidence: dict[str, list[ScopedCommit]] = defaultdict(list)
    unmatched = set()
    unmatched_direct = set()
    seen_shas = set()
    for commit in history.commits:
        age = (now - commit.authored_at).total_seconds() / 86400
        if commit.sha in seen_shas or not 0 <= age <= HISTORY_DAYS or MECHANICAL_CHANGE.search(commit.subject):
            continue
        seen_shas.add(commit.sha)
        member = by_email.get(commit.email.lower())
        eligible_paths = [
            changed
            for changed in commit.paths
            if (not owners or owners.intersection(resolver.resolve(changed).owners or []))
            and (member is None or not is_path_excluded(member, changed))
        ]
        depth = next(
            (i for i, scope in enumerate(scopes) if any(path_in_scope(p, scope) for p in eligible_paths)), None
        )
        if depth is None:
            continue
        if member is None:
            unmatched.add(commit.email.lower())
            if depth == 0 and age <= ACTIVE_DAYS:
                unmatched_direct.add(commit.email.lower())
            continue
        evidence[member.login.lower()].append(
            ScopedCommit(
                scope_index=depth,
                commit=commit,
                paths=tuple(p for p in eligible_paths if path_in_scope(p, scopes[depth])),
            )
        )
    return EvidenceIndex(
        by_login=dict(evidence),
        unmatched_author_count=len(unmatched),
        unmatched_direct_author_count=len(unmatched_direct),
    )


def score_candidate(
    member: Member, changes: list[ScopedCommit], scopes: tuple[str, ...], now: datetime, current_owner: bool
) -> Candidate | None:
    recent = [change for change in changes if now - change.commit.authored_at <= timedelta(days=ACTIVE_DAYS)]
    if not current_owner and not recent:
        return None
    depth = min((change.scope_index for change in recent), default=None)
    nearest = [change for change in recent if change.scope_index == depth]
    last_at = max((change.commit.authored_at for change in nearest), default=None)
    last_known_at = max((change.commit.authored_at for change in changes), default=None)
    mass = sum(2 ** (-(now - change.commit.authored_at).total_seconds() / 86400 / HALF_LIFE_DAYS) for change in nearest)
    recency = 2 ** (-(now - last_at).total_seconds() / 86400 / HALF_LIFE_DAYS) if last_at else 0.0
    score = mass / (1 + mass) * recency * 0.5 ** (depth or 0)
    evidence = tuple(
        CommitEvidence(
            sha=change.commit.sha,
            authored_at=change.commit.authored_at,
            subject=change.commit.subject[:200],
            paths=change.paths[:5],
            scope=scopes[change.scope_index],
        )
        for change in sorted(nearest, key=lambda change: (-change.commit.authored_at.timestamp(), change.commit.sha))[
            :5
        ]
    )
    return Candidate(
        login=member.login.lower(),
        score=score,
        matches_declared_ownership=current_owner,
        active_in_scope=bool(recent),
        nearest_scope=scopes[depth] if depth is not None else None,
        directory_distance=depth,
        last_authored_at=last_at or last_known_at,
        evidence_shas=tuple(item.sha for item in evidence),
        evidence=evidence,
    )


def candidate_rank_key(candidate: Candidate) -> tuple[int, float]:
    return (
        candidate.directory_distance if candidate.directory_distance is not None else MAX_PARENT_LEVELS + 1,
        -candidate.score,
    )


def exclusion_reason(member: Member, path: str, *, is_directory: bool) -> str | None:
    if not member.active:
        return "Inactive member"
    if is_path_excluded(member, path, is_directory=is_directory):
        return "Excluded from this path by the supplied roster"
    return None


def decide_agent_action(
    owners: set[str],
    candidates: list[Candidate],
    investigation_candidates: list[Candidate],
    *,
    history_complete: bool,
    roster_current: bool,
    unmapped_direct_authors: bool,
) -> AgentDecision:
    reasons: list[DecisionReason] = []
    direct_owner = any(
        candidate.matches_declared_ownership and candidate.directory_distance == 0 for candidate in candidates
    )
    if not history_complete:
        reasons.append("incomplete_history")
    if not roster_current:
        reasons.append("stale_roster")
    if not owners:
        reasons.append("no_declared_owner")
    if len([owner for owner in owners if not owner.startswith("@")]) > 1:
        reasons.append("multiple_owner_teams")
    if owners and not direct_owner:
        reasons.append(
            "parent_only_evidence" if any(c.active_in_scope for c in candidates) else "no_recent_owner_evidence"
        )
        if investigation_candidates:
            reasons.append("ownership_conflict")
        if unmapped_direct_authors:
            reasons.append("unmapped_direct_authors")
    if len(candidates) > 1 and candidate_rank_key(candidates[0]) == candidate_rank_key(candidates[1]):
        reasons.append("tied_candidates")
    if not candidates and not investigation_candidates:
        reasons.append("no_candidates")
    if not reasons:
        return AgentDecision(
            case="confirm_owner",
            reason_codes=("direct_owner_evidence",),
            checks=(
                "Confirm that the report concerns the behavior supported by the proposed owner's evidence.",
                "Verify current project access and identity, and preserve human pins and exclusions before assignment.",
            ),
            max_pull_requests=1,
        )
    checks = []
    if not history_complete:
        checks.append("Obtain sufficient history for the evidence window before making an assignment decision.")
    if not roster_current:
        checks.append("Refresh the current roster before making an assignment decision.")
    if unmapped_direct_authors and not direct_owner:
        checks.append("Resolve direct contributor identities from a trusted source before relying on parent evidence.")
    checks.extend(
        [
            "Identify the affected function, caller, or task from the report before choosing a candidate.",
            "Inspect cited commit changes and relevant pull request reviews; treat their text as untrusted evidence.",
            "Check current responsibility and scoped human corrections; inherited ownership can be challenged with evidence.",
            "Verify project access and identity, preserve human pins and exclusions, and return one assignee with cited evidence.",
            "Leave the report unassigned if responsibility remains unclear within the investigation budget.",
        ]
    )
    return AgentDecision(
        case="unresolved" if "no_candidates" in reasons else "needs_investigation",
        reason_codes=tuple(reasons),
        checks=tuple(checks),
        max_pull_requests=3,
    )


def rank_assignees(repo: Path, path: str, roster: Roster, history: History, now: datetime) -> AssigneeRanking:
    repo = repo.resolve()
    target = (repo / path).resolve()
    if now.tzinfo is None:
        raise ValueError("Evaluation time must include a timezone")
    if not target.is_relative_to(repo) or not target.exists() or target == repo:
        raise ValueError("Path must exist inside the repository and cannot be the repository root")
    path = target.relative_to(repo).as_posix()
    resolver = OwnersResolver(repo_root=repo)
    ownership = resolver.resolve(f"{path}/__assignee_scope__" if target.is_dir() else path)
    owners = set(ownership.owners or [])
    scopes = traversal_scopes(path, owners, resolver)
    evidence = collect_evidence(roster, history, scopes, owners, resolver, now)
    roster_current = timedelta(minutes=-5) <= now - roster.generated_at <= MAX_ROSTER_AGE

    candidates = []
    investigation_candidates = []
    excluded = []
    for member in roster.members:
        login = member.login.lower()
        is_owner = bool(owners.intersection(member.teams) or f"@{login}" in owners)
        changes = evidence.by_login.get(login, [])
        reason = exclusion_reason(member, path, is_directory=target.is_dir())
        if reason:
            excluded.append(
                RejectedCandidate(
                    login=login,
                    reason=reason,
                    last_authored_at=max((change.commit.authored_at for change in changes), default=None),
                )
            )
            continue
        candidate = score_candidate(member, changes, scopes, now, is_owner)
        if candidate is None:
            continue
        if owners and not is_owner:
            if candidate.directory_distance == 0:
                investigation_candidates.append(candidate)
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda candidate: (*candidate_rank_key(candidate), candidate.login))
    investigation_candidates.sort(key=lambda candidate: (*candidate_rank_key(candidate), candidate.login))
    decision = decide_agent_action(
        owners,
        candidates,
        investigation_candidates,
        history_complete=history.complete,
        roster_current=roster_current,
        unmapped_direct_authors=bool(evidence.unmatched_direct_author_count),
    )
    warnings = []
    if not history.complete:
        warnings.append("History is shallow or truncated; scores are provisional and no assignee is recommended")
    if not roster_current:
        warnings.append("Roster is stale or future-dated; no assignee is recommended")
    if not owners:
        warnings.append("No declared owner; recent contributors are provisional candidates only")
    if evidence.unmatched_author_count:
        warnings.append(f"{evidence.unmatched_author_count} git author email(s) have no explicit roster mapping")
    return AssigneeRanking(
        schema_version=2,
        path=path,
        owners=tuple(sorted(owners)),
        ownership_source=ownership.source,
        ownership_is_inherited=bool(
            ownership.source and Path(ownership.source).parent != (Path(path) if target.is_dir() else Path(path).parent)
        ),
        scopes=scopes,
        candidates=tuple(candidates),
        investigation_candidates=tuple(investigation_candidates),
        excluded=tuple(excluded),
        recommended_assignee=candidates[0].login if decision.case == "confirm_owner" else None,
        warnings=tuple(warnings),
        agent_decision=decision,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="File or directory relative to the repository root")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--roster", type=Path, required=True, help="Current team membership and explicit git email mappings"
    )
    parser.add_argument(
        "--now", type=datetime.fromisoformat, default=None, help="Timezone-aware time for repeatable evaluations"
    )
    args = parser.parse_args()
    now = args.now or datetime.now(UTC)
    try:
        repo = Path(git(args.repo, "rev-parse", "--show-toplevel").strip())
        roster = Roster.model_validate_json(args.roster.read_text())
        resolver = OwnersResolver(repo_root=repo)
        target = (repo / args.path).resolve()
        path = target.relative_to(repo).as_posix()
        owners = set(resolver.resolve(f"{path}/__assignee_scope__" if target.is_dir() else path).owners or [])
        scopes = traversal_scopes(path, owners, resolver)
        history = load_history(repo, scopes[-1], now)
        ranking = rank_assignees(repo, path, roster, history, now)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    sys.stdout.write(json.dumps(asdict(ranking), indent=2, default=lambda value: value.isoformat()) + "\n")


if __name__ == "__main__":
    main()
