# ruff: noqa: T201 allow print statements
"""A report on the skills that the MCP `learn` command serves, for the team that owns the served list."""

from __future__ import annotations

import re
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import discovery, linting, skill_audience, skill_manifest, skill_size, tool_references

# Scout and ReviewHog skills are copied into each project's skill store, where an agent reads them
# with `skill-get`. A served skill that names one is not sending the agent to `learn`. The harnesses
# enforce these prefixes: SIGNALS_SCOUT_SKILL_PREFIX in products/signals/backend/scout_harness and
# the REVIEW_HOG_*_PREFIX constants in products/review_hog/backend/reviewer/lazy_seed.py.
STORE_SKILL_PREFIXES = ("signals-scout-", "review-hog-")

HISTORY_DAYS = 90
LARGEST_SKILLS_SHOWN = 15
BOT_SHARE_SKILLS_SHOWN = 15
MIN_COMMITS_FOR_BOT_SHARE = 3
# A skill that names one optional gated tool among many still works for a caller without the flag.
FLAG_MISMATCH_MIN_SHARE = 0.5
# `learn` returns a heading outline, not the text, for a file above LEARN_OUTPUT_CHAR_LIMIT in
# services/mcp/src/skills/skill-catalog.ts.
LEARN_OUTPUT_CHAR_LIMIT = 44_000
_NAME_BOUNDARY = r"(?<![A-Za-z0-9_/-])({})(?![A-Za-z0-9_-])"
_TOOL_MENTION = r"(?:`|posthog:)({})(?![A-Za-z0-9_-])"


@dataclass(frozen=True)
class ServedSkill:
    name: str
    skill: skill_manifest.DiscoveredSkill
    feature_flag: str | None
    owners: tuple[str, ...]

    @property
    def root(self) -> Path:
        """The directory or loose file that holds the whole skill."""
        return self.skill.source_file.parent if self.skill.depth == 1 else self.skill.source_file


@dataclass(frozen=True)
class Pointer:
    skill: ServedSkill
    source_label: str
    line: int
    target: str


@dataclass(frozen=True)
class FlagMismatch:
    skill: ServedSkill
    tools_by_flag: dict[str, int]


@dataclass(frozen=True)
class SkillSize:
    skill: ServedSkill
    size: int
    size_before: int | None
    entry: skill_size.EntrySize


@dataclass(frozen=True)
class CommitShare:
    skill: ServedSkill
    commits: int
    bot_commits: int


@dataclass(frozen=True)
class UpkeepReport:
    served: list[ServedSkill]
    pointers: list[Pointer]
    flag_mismatches: list[FlagMismatch]
    sizes: list[SkillSize]
    measured_before: bool
    commit_shares: list[CommitShare] | None


def _owners(product_dir: Path) -> tuple[str, ...]:
    product_file = product_dir / "product.yaml"
    if not product_file.is_file():
        return ()
    owners = (yaml.safe_load(product_file.read_text()) or {}).get("owners") or []
    return tuple(str(owner) for owner in owners)


def _name_pattern(template: str, names: set[str]) -> re.Pattern[str] | None:
    if not names:
        return None
    return re.compile(template.format("|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))))


def _markdown_files(skill: skill_manifest.DiscoveredSkill) -> list[Path]:
    return [path for path in linting._lint_files(skill) if path.name.endswith((".md", ".md.j2"))]


def _load_served(repo_root: Path, skills: list[skill_manifest.DiscoveredSkill]) -> tuple[list[ServedSkill], set[str]]:
    """Return the served product skills, and the names of the product skills that are not served."""
    entries: dict[str, dict[str, object]] = json.loads((repo_root / skill_audience.SERVED_SKILLS_FILE).read_text())[
        "skills"
    ]
    served: list[ServedSkill] = []
    unserved: set[str] = set()
    for skill in skills:
        name = discovery._unrendered_skill_name(skill)
        entry = entries.get(name)
        if entry is None:
            unserved.add(name)
            continue
        flag = entry.get("feature_flag")
        served.append(ServedSkill(name, skill, str(flag) if flag else None, _owners(skill.product_dir)))
    return served, unserved


def _find_pointers(repo_root: Path, served: list[ServedSkill], unserved: set[str]) -> list[Pointer]:
    pattern = _name_pattern(_NAME_BOUNDARY, {name for name in unserved if not name.startswith(STORE_SKILL_PREFIXES)})
    if pattern is None:
        return []
    pointers: list[Pointer] = []
    for entry in served:
        for path in _markdown_files(entry.skill):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                pointers.extend(
                    Pointer(entry, str(path.relative_to(repo_root)), number, match.group(1))
                    for match in pattern.finditer(line)
                )
    return pointers


def _load_tool_flags(repo_root: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for rel_path in tool_references._MCP_SCHEMA_FILES:
        schema_file = repo_root / rel_path
        if not schema_file.is_file():
            continue
        for name, definition in json.loads(schema_file.read_text()).items():
            if definition.get("feature_flag"):
                flags[name] = definition["feature_flag"]
    return flags


def _find_flag_mismatches(
    served: list[ServedSkill], tool_names: set[str], tool_flags: dict[str, str]
) -> list[FlagMismatch]:
    """Half or more of the tools a skill names sit behind a flag that its list entry does not declare.

    A caller without that flag gets the skill and cannot call most of its tools.
    """
    pattern = _name_pattern(_TOOL_MENTION, tool_names)
    if pattern is None:
        return []
    mismatches: list[FlagMismatch] = []
    for entry in served:
        tools = {
            match.group(1) for path in _markdown_files(entry.skill) for match in pattern.finditer(path.read_text())
        }
        by_flag = Counter(
            tool_flags[tool] for tool in tools if tool in tool_flags and tool_flags[tool] != entry.feature_flag
        )
        if tools and sum(by_flag.values()) / len(tools) >= FLAG_MISMATCH_MIN_SHARE:
            mismatches.append(FlagMismatch(entry, dict(by_flag)))
    return mismatches


def _tree_size(root: Path) -> int | None:
    if root.is_file():
        return root.stat().st_size
    if not root.is_dir():
        return None
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _measure_sizes(repo_root: Path, served: list[ServedSkill], before_root: Path | None) -> list[SkillSize]:
    sizes: list[SkillSize] = []
    for entry in served:
        before = _tree_size(before_root / entry.root.relative_to(repo_root)) if before_root else None
        sizes.append(
            SkillSize(entry, _tree_size(entry.root) or 0, before, skill_size.measure_entry(entry.skill.source_file))
        )
    return sizes


def _count_commits(repo_root: Path, served: list[ServedSkill]) -> list[CommitShare] | None:
    """Count the commits that touched each served skill, and how many a bot account authored.

    Returns None outside a git checkout, or in one without the history.
    """
    try:
        log = subprocess.run(
            [
                "git",
                "log",
                f"--since={HISTORY_DAYS}.days",
                "--format=%x00%an",
                "--name-only",
                "--",
                ":(glob)products/*/skills/**",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    roots = {str(entry.root.relative_to(repo_root)): entry for entry in served}
    commits: dict[str, int] = defaultdict(int)
    bot_commits: dict[str, int] = defaultdict(int)
    for block in log.split("\x00")[1:]:
        author, *paths = block.strip().splitlines()
        touched = {
            entry.name for root, entry in roots.items() for path in paths if path == root or path.startswith(f"{root}/")
        }
        for name in touched:
            commits[name] += 1
            bot_commits[name] += author.endswith("[bot]")
    return [CommitShare(entry, commits[entry.name], bot_commits[entry.name]) for entry in served if commits[entry.name]]


def build_report(
    repo_root: Path, skills: list[skill_manifest.DiscoveredSkill], before_root: Path | None = None
) -> UpkeepReport:
    served, unserved = _load_served(repo_root, skills)
    return UpkeepReport(
        served=served,
        pointers=_find_pointers(repo_root, served, unserved),
        flag_mismatches=_find_flag_mismatches(
            served, tool_references._load_mcp_tool_names(repo_root) or set(), _load_tool_flags(repo_root)
        ),
        sizes=_measure_sizes(repo_root, served, before_root),
        measured_before=before_root is not None,
        commit_shares=_count_commits(repo_root, served),
    )


def _owner_label(entry: ServedSkill) -> str:
    return ", ".join(entry.owners) or "no owner"


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB"


def _size_change(size: SkillSize, measured_before: bool) -> str:
    if not measured_before:
        return "not measured"
    if size.size_before is None:
        return "new"
    return f"{(size.size - size.size_before) / 1024:+.1f} KB"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = [f"| {' | '.join(header)} |", f"|{'|'.join(' --- ' for _ in header)}|"]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return [*lines, ""]


def render_markdown(report: UpkeepReport) -> str:
    flagged = sum(1 for entry in report.served if entry.feature_flag)
    lines = [
        "# Served skills upkeep",
        "",
        f"`learn` serves {len(report.served)} product skills, {flagged} of them behind a feature flag.",
        "",
        f"## Served skills that name a skill `learn` does not serve ({len(report.pointers)})",
        "",
    ]
    if report.pointers:
        lines += _table(
            ["Skill", "Owner", "Where", "Names"],
            [
                [f"`{p.skill.name}`", _owner_label(p.skill), f"`{p.source_label}:{p.line}`", f"`{p.target}`"]
                for p in report.pointers
            ],
        )
    else:
        lines += ["None.", ""]

    lines += [
        f"## Served skills with most tools behind a flag the list does not declare ({len(report.flag_mismatches)})",
        "",
    ]
    if report.flag_mismatches:
        lines += _table(
            ["Skill", "Owner", "Listed flag", "Tools behind another flag"],
            [
                [
                    f"`{m.skill.name}`",
                    _owner_label(m.skill),
                    f"`{m.skill.feature_flag}`" if m.skill.feature_flag else "none",
                    ", ".join(f"`{flag}` ({count})" for flag, count in sorted(m.tools_by_flag.items())),
                ]
                for m in report.flag_mismatches
            ],
        )
    else:
        lines += ["None.", ""]

    long_entries = sorted(
        (s for s in report.sizes if s.entry.over_recommendation), key=lambda s: s.entry.chars, reverse=True
    )
    lines += [
        f"## Served skills with a `SKILL.md` over {skill_size.RECOMMENDED_ENTRY_LINES} lines "
        f"or about {skill_size.RECOMMENDED_ENTRY_TOKENS:,} tokens ({len(long_entries)})",
        "",
    ]
    if long_entries:
        lines += _table(
            ["Skill", "Owner", "Lines", "Tokens (about)", "`learn` returns"],
            [
                [
                    f"`{s.skill.name}`",
                    _owner_label(s.skill),
                    str(s.entry.lines),
                    f"{s.entry.tokens:,}",
                    "an outline only" if s.entry.chars > LEARN_OUTPUT_CHAR_LIMIT else "the full text",
                ]
                for s in long_entries
            ],
        )
    else:
        lines += ["None.", ""]

    largest = sorted(report.sizes, key=lambda s: s.size, reverse=True)[:LARGEST_SKILLS_SHOWN]
    lines += [f"## Largest served skills (top {len(largest)})", ""]
    lines += _table(
        ["Skill", "Owner", "Size", f"Change in {HISTORY_DAYS} days"],
        [
            [
                f"`{s.skill.name}`",
                _owner_label(s.skill),
                _kb(s.size),
                _size_change(s, report.measured_before),
            ]
            for s in largest
        ],
    )

    lines += [f"## Largest share of commits by bot accounts in {HISTORY_DAYS} days", ""]
    if report.commit_shares is None:
        lines += ["Not measured: this checkout has no git history.", ""]
    else:
        busy = sorted(
            (c for c in report.commit_shares if c.commits >= MIN_COMMITS_FOR_BOT_SHARE and c.bot_commits),
            key=lambda c: c.bot_commits / c.commits,
            reverse=True,
        )[:BOT_SHARE_SKILLS_SHOWN]
        if busy:
            lines += _table(
                ["Skill", "Owner", "Commits", "By a bot"],
                [
                    [f"`{c.skill.name}`", _owner_label(c.skill), str(c.commits), f"{c.bot_commits / c.commits:.0%}"]
                    for c in busy
                ],
            )
        else:
            lines += ["None.", ""]
    return "\n".join(lines)


def summary(report: UpkeepReport) -> dict[str, int]:
    """The counts a caller posts when the full report is too long for its channel."""
    return {
        "served": len(report.served),
        "pointers": len(report.pointers),
        "flag_mismatches": len(report.flag_mismatches),
        "over_recommended_size": sum(1 for size in report.sizes if size.entry.over_recommendation),
        "outline_only": sum(1 for size in report.sizes if size.entry.chars > LEARN_OUTPUT_CHAR_LIMIT),
    }
