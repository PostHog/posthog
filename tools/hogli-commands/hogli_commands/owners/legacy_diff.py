"""Equivalence differ: legacy ``CODEOWNERS-soft`` + ``product.yaml`` vs the new resolver.

The auto-assigner unions owners across every matching soft rule (see
``.github/scripts/assign-reviewers.js`` ``computeOwnerFootprints``) and synthesizes
a ``products/<name>/**`` rule per ``product.yaml`` (``loadProductYamlRules``, skipping
``@handles`` and ``team-CHANGEME``). This reproduces that OLD footprint and compares it
to the NEW resolver result, classifying every tracked path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from .conversion import parse_soft_file
from .matcher import compile_pattern, normalize_path
from .resolver import OwnersResolver
from .schema import CHANGEME_SLUG


class DiffClass(str, Enum):
    IDENTICAL = "IDENTICAL"
    NARROWED = "NARROWED"
    ORPHANED = "ORPHANED"
    EXPANDED = "EXPANDED"
    NEWLY_OWNED = "NEWLY_OWNED"


@dataclass
class LegacyRule:
    pattern: str
    owners: list[str]


def synthesize_product_rules(repo_root: Path) -> list[LegacyRule]:
    """Recreate ``loadProductYamlRules``: a ``products/<name>/**`` rule per product,
    with ``@handles`` and ``team-CHANGEME`` skipped (only auto-assignable team slugs)."""
    rules: list[LegacyRule] = []
    products_dir = repo_root / "products"
    if not products_dir.is_dir():
        return rules
    for entry in sorted(products_dir.iterdir()):
        product_yaml = entry / "product.yaml"
        if not entry.is_dir() or not product_yaml.is_file():
            continue
        data = yaml.safe_load(product_yaml.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("owners"), list):
            continue
        owners = [
            o for o in data["owners"] if isinstance(o, str) and o and o != CHANGEME_SLUG and not o.startswith("@")
        ]
        if owners:
            rules.append(LegacyRule(pattern=f"products/{entry.name}/**", owners=owners))
    return rules


class LegacyOwners:
    """OLD owner resolution: union across all matching soft + product.yaml rules.

    ``soft_text`` is the ``CODEOWNERS-soft`` contents. It is passed in explicitly
    (rather than read from disk) because the file is deleted post-migration — the
    differ is a migration-era tool that runs against the file's git history."""

    def __init__(self, repo_root: Path, soft_text: str) -> None:
        soft_rules = parse_soft_file(soft_text) if soft_text else []
        self._rules: list[LegacyRule] = [LegacyRule(r.pattern, r.owners) for r in soft_rules]
        self._rules.extend(synthesize_product_rules(repo_root))
        self._matchers = [(compile_pattern(r.pattern), r.owners) for r in self._rules]

    def owners_of(self, path: str) -> set[str]:
        norm = normalize_path(path)
        owners: set[str] = set()
        for matcher, rule_owners in self._matchers:
            if matcher.test(norm):
                owners.update(rule_owners)
        return owners


def classify(old: set[str], new: set[str]) -> DiffClass:
    if old == new:
        return DiffClass.IDENTICAL
    if not new:
        return DiffClass.ORPHANED
    if not old:
        return DiffClass.NEWLY_OWNED
    if new - old:
        return DiffClass.EXPANDED
    return DiffClass.NARROWED


@dataclass
class PathDiff:
    path: str
    old: set[str]
    new: set[str]
    klass: DiffClass


@dataclass
class DiffReport:
    diffs: list[PathDiff]

    def by_class(self, klass: DiffClass) -> list[PathDiff]:
        return [d for d in self.diffs if d.klass == klass]

    @property
    def counts(self) -> dict[DiffClass, int]:
        result = dict.fromkeys(DiffClass, 0)
        for d in self.diffs:
            result[d.klass] += 1
        return result

    @property
    def violates_invariants(self) -> bool:
        return bool(self.by_class(DiffClass.ORPHANED) or self.by_class(DiffClass.EXPANDED))


def diff_all(repo_root: Path, soft_text: str, resolver: OwnersResolver | None = None) -> DiffReport:
    resolver = resolver or OwnersResolver(repo_root)
    legacy = LegacyOwners(repo_root, soft_text)
    diffs: list[PathDiff] = []
    for path in resolver.tracked_files():
        old = legacy.owners_of(path)
        resolution = resolver.resolve(path)
        new = set(resolution.owners or [])
        diffs.append(PathDiff(path=path, old=old, new=new, klass=classify(old, new)))
    return DiffReport(diffs=diffs)


def render_markdown(report: DiffReport) -> str:
    lines = ["# Legacy ownership equivalence report", ""]
    lines.append("| Class | Count |")
    lines.append("| --- | --- |")
    for klass, count in report.counts.items():
        lines.append(f"| {klass.value} | {count} |")
    lines.append("")
    for klass in (DiffClass.ORPHANED, DiffClass.EXPANDED, DiffClass.NARROWED, DiffClass.NEWLY_OWNED):
        entries = report.by_class(klass)
        if not entries:
            continue
        lines.append(f"## {klass.value} ({len(entries)})")
        lines.append("")
        lines.append("| Path | Old | New |")
        lines.append("| --- | --- | --- |")
        for d in sorted(entries, key=lambda e: e.path):
            old = ", ".join(sorted(d.old)) or "—"
            new = ", ".join(sorted(d.new)) or "—"
            lines.append(f"| `{d.path}` | {old} | {new} |")
        lines.append("")
    return "\n".join(lines) + "\n"
