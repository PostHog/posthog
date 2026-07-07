"""One-off conversion of ``.github/CODEOWNERS-soft`` into distributed ``owners.yaml``.

Committed so the translation is reviewable and rerunnable, but not meant to run
against the tree on every invocation — it emits files for inspection and the
legacy differ proves equivalence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_GLOB_CHARS = re.compile(r"[*?]")
_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


@dataclass
class SoftRule:
    pattern: str
    owners: list[str]


@dataclass
class GeneratedFile:
    directory: str  # repo-relative posix ("" = root)
    owners: list[str] | None  # None = explicit unowned-by-design
    rules: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class ConversionSummary:
    files: dict[str, GeneratedFile] = field(default_factory=dict)
    redundant_skips: list[str] = field(default_factory=list)
    needs_decision: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _normalize_owner(token: str) -> str:
    """``@PostHog/team-x`` → ``team-x``; ``@handle`` stays ``@handle``."""
    if token.startswith("@PostHog/"):
        return token[len("@PostHog/") :]
    return token


def parse_soft_file(text: str) -> list[SoftRule]:
    rules: list[SoftRule] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        pattern = tokens[0]
        owners = [_normalize_owner(t) for t in tokens[1:]]
        rules.append(SoftRule(pattern=pattern, owners=owners))
    return rules


def _dir_level_target(pattern: str, repo_root: Path) -> str | None:
    """The directory a whole-directory pattern maps to, or None if it's a
    filename/glob pattern that must become a rule."""
    candidate: str | None = None
    if pattern.endswith("/"):
        candidate = pattern.rstrip("/")
    elif pattern.endswith("/**"):
        candidate = pattern[:-3]
    elif not _GLOB_CHARS.search(pattern) and (repo_root / pattern).is_dir():
        candidate = pattern
    if candidate is None or _GLOB_CHARS.search(candidate):
        # A glob anywhere in the directory part (e.g. `.agents/skills/ingestion-*/`)
        # cannot become a real directory — it must be a rule in a static ancestor.
        return None
    # A single-segment pattern with at most a trailing slash (`bin/`, `.claude/`) is
    # unanchored in CODEOWNERS — it matches a `bin` dir at ANY depth (ee/bin,
    # frontend/bin). Mapping it to the root-level directory would orphan the deeper
    # matches, so it must stay a root rule with its original semantics.
    stripped = pattern[:-1] if pattern.endswith("/") else pattern
    if "/" not in stripped:
        return None
    return candidate


def _rule_target(pattern: str) -> tuple[str, str]:
    """(directory, match) for a filename/glob pattern: the deepest static ancestor
    directory, and the match glob anchored within it."""
    stripped = pattern[:-1] if pattern.endswith("/") else pattern
    if "/" not in stripped:
        # Unanchored (slash-free) pattern: keep its any-depth semantics at the root.
        return "", pattern
    segs = pattern.split("/")
    first_glob = next((i for i, s in enumerate(segs) if _GLOB_CHARS.search(s)), None)
    if first_glob is None:
        dir_segs, rem_segs = segs[:-1], segs[-1:]
    else:
        dir_segs, rem_segs = segs[:first_glob], segs[first_glob:]
    directory = "/".join(dir_segs)
    remainder = "/".join(rem_segs)
    # A slash-free / root-level pattern keeps its original any-depth semantics; a
    # pattern moved under a directory is re-anchored at that directory with a `/`.
    match = pattern if directory == "" else "/" + remainder
    return directory, match


class Converter:
    """Translates soft rules into per-directory generated files."""

    def __init__(self, repo_root: Path, product_owners: dict[str, list[str]]) -> None:
        self.repo_root = repo_root
        # product name -> normalized product.yaml owners (CHANGEME/empty already applied)
        self.product_owners = product_owners
        self.summary = ConversionSummary()

    def _file_for(self, directory: str) -> GeneratedFile:
        gen = self.summary.files.get(directory)
        if gen is None:
            # A rules-only file must stay transparent to ancestor ownership, so its
            # default is the empty list ("no contribution"), not the explicit null
            # reset. The repo root is the exception: no repo-wide default owner is a
            # decision, rendered as `owners: null` (see render_owners_yaml).
            gen = GeneratedFile(directory=directory, owners=[])
            self.summary.files[directory] = gen
        return gen

    def _handle_products_rule(self, rule: SoftRule) -> bool:
        """Returns True if the rule was fully handled here (redundant/needs-decision)."""
        segs = rule.pattern.split("/")
        if len(segs) < 2 or segs[0] != "products":
            return False
        name = segs[1]
        whole_product = rule.pattern in (f"products/{name}/", f"products/{name}/**")
        if not whole_product:
            return False  # sub-path: fall through to normal dir/rule generation

        product = set(self.product_owners.get(name, []))
        soft = set(rule.owners)
        if soft == product:
            self.summary.redundant_skips.append(f"{rule.pattern} (covered by products/{name}/product.yaml)")
        else:
            self.summary.needs_decision.append(
                f"{rule.pattern}: soft owners {sorted(soft)} differ from "
                f"products/{name}/product.yaml owners {sorted(product)}"
            )
        return True

    def add_rule(self, rule: SoftRule) -> None:
        if not rule.owners:
            return  # owner-less reset lines carry no soft ownership
        if self._handle_products_rule(rule):
            return

        directory = _dir_level_target(rule.pattern, self.repo_root)
        if directory is not None:
            gen = self._file_for(directory)
            if not gen.owners:
                gen.owners = list(rule.owners)
            elif gen.owners != rule.owners:
                self.summary.notes.append(
                    f"{rule.pattern}: overrides existing default owners for {directory or '<root>'}"
                )
                gen.owners = list(rule.owners)
            return

        rule_dir, match = _rule_target(rule.pattern)
        self._file_for(rule_dir).rules.append((match, list(rule.owners)))

    def convert(self, soft_rules: list[SoftRule]) -> ConversionSummary:
        for rule in soft_rules:
            self.add_rule(rule)
        return self.summary


def _scalar(value: str) -> str:
    if _PLAIN_SAFE.match(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _flow_list(owners: list[str]) -> str:
    return "[" + ", ".join(_scalar(o) for o in owners) + "]"


def render_owners_yaml(gen: GeneratedFile) -> str:
    lines = ["version: 1"]
    if gen.owners is None or (gen.directory == "" and not gen.owners):
        # Root: no repo-wide default owner, and that's a decision — explicit null.
        lines.append("owners: null")
    else:
        lines.append(f"owners: {_flow_list(gen.owners)}")
    if gen.rules:
        lines.append("rules:")
        for match, owners in gen.rules:
            lines.append(f"  - match: {_scalar(match)}")
            lines.append(f"    owners: {_flow_list(owners)}")
    return "\n".join(lines) + "\n"


def write_generated_files(summary: ConversionSummary, repo_root: Path, *, dry_run: bool = False) -> list[str]:
    """Write each generated ``owners.yaml``. Returns the sorted repo-relative paths."""
    written: list[str] = []
    for directory in sorted(summary.files):
        gen = summary.files[directory]
        rel = f"{directory}/owners.yaml" if directory else "owners.yaml"
        written.append(rel)
        if dry_run:
            continue
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_owners_yaml(gen))
    return written
