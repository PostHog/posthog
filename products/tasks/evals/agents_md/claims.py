import re
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from posthog.dataclasses import frozen

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS_MD_PATH = REPO_ROOT / "AGENTS.md"
CLAIMS_PATH = Path(__file__).with_name("claims.json")

Arm = Literal["with", "without"]
ARMS: tuple[Arm, ...] = ("with", "without")

REVIEW_BULLET = re.compile(r"^- .*`\[review\]`")
HEADING = re.compile(r"^#{2,3} (?P<title>.+)$")


@dataclass(frozen=True, kw_only=True, slots=True)
class Claim:
    """One `[review]` bullet in AGENTS.md, with the trap task and detectors that test it."""

    id: str
    section: str
    line: str
    task: str | None
    detectors: tuple[dict[str, Any], ...]
    untestable: str | None
    no_change_is_compliant: bool = False

    @property
    def text(self) -> str:
        return self.line.removeprefix("- ")

    @property
    def testable(self) -> bool:
        return self.task is not None


@frozen
class ReviewBullet:
    section: str
    line: str


def review_bullets(agents_md: str) -> list[ReviewBullet]:
    """Every `[review]` bullet with the heading above it."""
    section = ""
    bullets: list[ReviewBullet] = []
    for line in agents_md.splitlines():
        heading = HEADING.match(line)
        if heading:
            section = heading.group("title")
        elif REVIEW_BULLET.match(line):
            bullets.append(ReviewBullet(section=section, line=line))
    return bullets


def _entries_for(line: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every entry for one bullet; a rule can have several trap tasks, each its own claim."""
    matches = [entry for entry in entries if line.startswith(f"- {entry['starts_with']}")]
    if not matches:
        raise ValueError(f"No claims.json entry matches the AGENTS.md rule: {line[:80]}")
    return matches


def load_claims(agents_md: str | None = None, claims_path: Path = CLAIMS_PATH) -> list[Claim]:
    """Pair every `[review]` bullet with its claims.json entry, and fail loudly when one side is missing."""
    text = AGENTS_MD_PATH.read_text() if agents_md is None else agents_md
    entries: list[dict[str, Any]] = json.loads(claims_path.read_text())
    claims = [
        Claim(
            id=entry["id"],
            section=bullet.section,
            line=bullet.line,
            task=entry.get("task"),
            detectors=tuple(entry.get("detectors", ())),
            untestable=entry.get("untestable"),
            no_change_is_compliant=entry.get("no_change_is_compliant", False),
        )
        for bullet in review_bullets(text)
        for entry in _entries_for(bullet.line, entries)
    ]
    unused = {entry["id"] for entry in entries} - {claim.id for claim in claims}
    if unused:
        raise ValueError(f"claims.json entries match no AGENTS.md rule: {sorted(unused)}")
    return claims


def select_claims(claims: Iterable[Claim], ids: Iterable[str]) -> list[Claim]:
    by_id = {claim.id: claim for claim in claims}
    unknown = sorted(set(ids) - by_id.keys())
    if unknown:
        raise ValueError(f"Unknown claims: {unknown}")
    return [by_id[claim_id] for claim_id in ids]


def ablate(agents_md: str, claim: Claim) -> str:
    """AGENTS.md without the one bullet under test, so the two arms differ by that line only."""
    lines = agents_md.splitlines(keepends=True)
    kept = [line for line in lines if line.rstrip("\n") != claim.line]
    if len(kept) != len(lines) - 1:
        raise ValueError(f"The rule is not in AGENTS.md exactly once: {claim.id}")
    return "".join(kept)


def agents_md_for(agents_md: str, claim: Claim, arm: Arm, candidate: str | None = None) -> str:
    if candidate is not None:
        return candidate if arm == "with" else agents_md
    return agents_md if arm == "with" else ablate(agents_md, claim)


def build_prompt(claim: Claim) -> str:
    if claim.task is None:
        raise ValueError(f"The claim has no task: {claim.id}")
    return (
        "You are working in a checkout of the PostHog repository. "
        "Implement the change described below by editing files in the working directory. "
        "Do not install dependencies, set up an environment, or run the test suite. "
        "Do not commit. Stop when the change is complete.\n\n"
        f"{claim.task}\n"
    )
