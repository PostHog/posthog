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
class Candidate:
    login: str
    score: float
    current_owner: bool
    active_in_scope: bool
    nearest_scope: str | None
    directory_distance: int | None
    last_authored_at: datetime | None
    evidence_shas: tuple[str, ...]


@frozen
class RejectedCandidate:
    login: str
    reason: str
    last_authored_at: datetime | None


@frozen
class AssigneeRanking:
    path: str
    owners: tuple[str, ...]
    ownership_source: str | None
    scopes: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    excluded: tuple[RejectedCandidate, ...]
    recommended_assignee: str | None
    warnings: tuple[str, ...]


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
    warnings = []
    if not history.complete:
        warnings.append("History is shallow or truncated; scores are provisional and no assignee is recommended")
    roster_current = timedelta(minutes=-5) <= now - roster.generated_at <= MAX_ROSTER_AGE
    if not roster_current:
        warnings.append("Roster is stale or future-dated; no assignee is recommended")
    if not owners:
        warnings.append("No declared owner; recent contributors are provisional candidates only")

    by_email = {email.lower(): member for member in roster.members for email in member.emails}
    evidence: dict[str, list[tuple[int, Commit]]] = defaultdict(list)
    unmatched = set()
    seen_shas = set()
    for commit in history.commits:
        age = (now - commit.authored_at).total_seconds() / 86400
        if commit.sha in seen_shas or not 0 <= age <= HISTORY_DAYS or MECHANICAL_CHANGE.search(commit.subject):
            continue
        seen_shas.add(commit.sha)
        eligible_paths = [
            changed
            for changed in commit.paths
            if not owners or owners.intersection(resolver.resolve(changed).owners or [])
        ]
        depth = next(
            (i for i, scope in enumerate(scopes) if any(path_in_scope(p, scope) for p in eligible_paths)), None
        )
        if depth is None:
            continue
        member = by_email.get(commit.email.lower())
        if member is None:
            unmatched.add(commit.email.lower())
            continue
        evidence[member.login.lower()].append((depth, commit))
    if unmatched:
        warnings.append(f"{len(unmatched)} git author email(s) have no explicit roster mapping")

    candidates = []
    excluded = []
    for member in roster.members:
        login = member.login.lower()
        is_owner = bool(owners.intersection(member.teams) or f"@{login}" in owners)
        reason = (
            "Inactive member"
            if not member.active
            else "Excluded from this path by the supplied roster"
            if any(compile_pattern(pattern).test(path) for pattern in member.excluded_paths)
            else "Outside the current owning team"
            if owners and not is_owner
            else None
        )
        if reason:
            excluded.append(
                RejectedCandidate(
                    login=login,
                    reason=reason,
                    last_authored_at=max((commit.authored_at for _, commit in evidence.get(login, [])), default=None),
                )
            )
            continue
        changes = evidence.get(login, [])
        recent = [
            (depth, commit) for depth, commit in changes if now - commit.authored_at <= timedelta(days=ACTIVE_DAYS)
        ]
        if not is_owner and not recent:
            continue
        depth = min((level for level, _ in recent), default=None)
        nearest = [commit for level, commit in recent if level == depth]
        last_at = max((commit.authored_at for commit in nearest), default=None)
        last_known_at = max((commit.authored_at for _, commit in changes), default=None)
        mass = sum(2 ** (-(now - commit.authored_at).total_seconds() / 86400 / HALF_LIFE_DAYS) for commit in nearest)
        recency = 2 ** (-(now - last_at).total_seconds() / 86400 / HALF_LIFE_DAYS) if last_at else 0.0
        score = mass / (1 + mass) * recency * 0.5 ** (depth or 0)
        candidates.append(
            Candidate(
                login=login,
                score=score,
                current_owner=is_owner,
                active_in_scope=bool(recent),
                nearest_scope=scopes[depth] if depth is not None else None,
                directory_distance=depth,
                last_authored_at=last_at or last_known_at,
                evidence_shas=tuple(
                    commit.sha for commit in sorted(nearest, key=lambda c: c.authored_at, reverse=True)[:5]
                ),
            )
        )

    def rank_key(candidate: Candidate) -> tuple[int, float]:
        return (
            candidate.directory_distance if candidate.directory_distance is not None else len(scopes),
            -candidate.score,
        )

    candidates.sort(key=lambda candidate: (*rank_key(candidate), candidate.login))
    recommended = None
    if candidates and owners and history.complete and roster_current:
        first = candidates[0]
        if len(candidates) == 1 or rank_key(first) < rank_key(candidates[1]):
            recommended = first.login
    return AssigneeRanking(
        path=path,
        owners=tuple(sorted(owners)),
        ownership_source=ownership.source,
        scopes=scopes,
        candidates=tuple(candidates),
        excluded=tuple(excluded),
        recommended_assignee=recommended,
        warnings=tuple(warnings),
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
