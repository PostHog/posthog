import json
import subprocess
from pathlib import Path

import pytest

from products.posthog_ai.scripts.build_skills import discovery, upkeep

SERVED = "services/mcp/src/skills/served-skills.json"


def _write_skill(repo: Path, name: str, body: str = "Body", product: str = "alpha") -> Path:
    skill_dir = repo / "products" / product / "skills" / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\nname: {name}\ndescription: A skill\n---\n{body}\n")
    return skill_file


def _write_repo(
    repo: Path,
    served: dict[str, dict[str, str]],
    tool_flags: dict[str, str] | None = None,
    open_tools: list[str] | None = None,
) -> None:
    served_file = repo / SERVED
    served_file.parent.mkdir(parents=True)
    served_file.write_text(json.dumps({"skills": served, "context_mill_skills": {}}))
    schema_file = repo / "services" / "mcp" / "schema" / "tool-definitions.json"
    schema_file.parent.mkdir(parents=True)
    tools: dict[str, dict[str, str]] = {tool: {"feature_flag": flag} for tool, flag in (tool_flags or {}).items()}
    tools.update({tool: {} for tool in open_tools or []})
    schema_file.write_text(json.dumps(tools))
    (repo / "products" / "alpha").mkdir(parents=True, exist_ok=True)
    (repo / "products" / "alpha" / "product.yaml").write_text("name: Alpha\nowners:\n    - team-alpha\n")


def _report(repo: Path, before_root: Path | None = None) -> upkeep.UpkeepReport:
    return upkeep.build_report(repo, discovery.SkillDiscoverer(repo / "products").discover(), before_root)


@pytest.mark.parametrize(
    "body,expected",
    [
        ("For a broken survey, follow `internal-runbook`.", ["internal-runbook"]),
        ("Use the served-sibling skill.", []),
        ("Read it with skill-get: `signals-scout-general`.", []),
        ("The internal-runbook-extra file is something else.", []),
    ],
    ids=["names-an-unserved-skill", "names-a-served-skill", "names-a-store-skill", "longer-name"],
)
def test_report_finds_served_skills_that_name_an_unserved_skill(tmp_path: Path, body: str, expected: list[str]) -> None:
    _write_repo(tmp_path, {"served-skill": {}, "served-sibling": {}})
    _write_skill(tmp_path, "served-skill", body)
    _write_skill(tmp_path, "served-sibling")
    _write_skill(tmp_path, "internal-runbook", "Use `served-skill`.")
    _write_skill(tmp_path, "signals-scout-general")

    report = _report(tmp_path)

    assert [(p.skill.name, p.target, p.line, p.skill.owners) for p in report.pointers] == [
        ("served-skill", name, 5, ("team-alpha",)) for name in expected
    ]


@pytest.mark.parametrize(
    "entry,body,expected",
    [
        ({}, "Call `gated-list`, then posthog:gated-get, then `open-tool`.", {"gate": 2}),
        ({"feature_flag": "other"}, "Call `gated-list`, then posthog:gated-get, then `open-tool`.", {"gate": 2}),
        ({"feature_flag": "gate"}, "Call `gated-list`, then posthog:gated-get, then `open-tool`.", None),
        ({}, "Call `open-tool`, `open-list` and `open-get`. `gated-get` is optional.", None),
    ],
    ids=["no-flag-listed", "another-flag-listed", "the-tools-flag-listed", "one-optional-gated-tool"],
)
def test_report_finds_skills_with_most_tools_behind_a_flag_the_list_does_not_declare(
    tmp_path: Path, entry: dict[str, str], body: str, expected: dict[str, int] | None
) -> None:
    tool_flags = {"gated-list": "gate", "gated-get": "gate", "gated-unused": "gate"}
    _write_repo(tmp_path, {"served-skill": entry}, tool_flags, open_tools=["open-tool", "open-list", "open-get"])
    _write_skill(tmp_path, "served-skill", body)

    report = _report(tmp_path)

    assert [m.tools_by_flag for m in report.flag_mismatches] == ([expected] if expected else [])


def test_report_measures_growth_against_an_older_checkout(tmp_path: Path) -> None:
    repo, before = tmp_path / "now", tmp_path / "before"
    _write_repo(repo, {"grown-skill": {}, "new-skill": {}})
    _write_skill(repo, "grown-skill", "x" * 3000)
    _write_skill(repo, "new-skill")
    old_size = _write_skill(before, "grown-skill", "x" * 1000).stat().st_size

    report = _report(repo, before)

    sizes = {s.skill.name: s for s in report.sizes}
    assert sizes["grown-skill"].size - (sizes["grown-skill"].size_before or 0) == 2000
    assert sizes["grown-skill"].size_before == old_size
    assert sizes["new-skill"].size_before is None
    assert "| `new-skill` | team-alpha |" in upkeep.render_markdown(report)
    assert "| new |" in upkeep.render_markdown(report)


@pytest.mark.parametrize(
    "body,row",
    [
        ("x" * 1_000, None),
        ("x" * 30_000, "the full text"),
        ("x\n" * 600, "the full text"),
        ("x" * 50_000, "an outline only"),
    ],
    ids=["short", "over-5000-tokens", "over-500-lines", "over-the-learn-limit"],
)
def test_report_lists_skills_with_a_long_entry_file(tmp_path: Path, body: str, row: str | None) -> None:
    _write_repo(tmp_path, {"served-skill": {}})
    _write_skill(tmp_path, "served-skill", body)

    report = _report(tmp_path)
    markdown = upkeep.render_markdown(report)

    assert ("| `served-skill` | team-alpha |" in markdown.split("## Largest served skills")[0]) is (row is not None)
    assert row is None or f"| {row} |" in markdown
    assert upkeep.summary(report)["over_recommended_size"] == (0 if row is None else 1)
    assert upkeep.summary(report)["outline_only"] == (1 if row == "an outline only" else 0)


def test_report_counts_commits_by_bot_accounts(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=tmp_path, check=True, capture_output=True)

    _write_repo(tmp_path, {"served-skill": {}})
    skill_file = _write_skill(tmp_path, "served-skill")
    other_file = _write_skill(tmp_path, "unserved-skill")
    git("init", "-q")
    for author, path in [("A Person", skill_file), ("posthog[bot]", skill_file), ("some[bot]", other_file)]:
        path.write_text(path.read_text() + "more\n")
        git("add", "-A")
        git("-c", f"user.name={author}", "-c", "user.email=dev@example.com", "commit", "-q", "-m", "change")

    report = _report(tmp_path)

    assert report.commit_shares is not None
    assert [(c.skill.name, c.commits, c.bot_commits) for c in report.commit_shares] == [("served-skill", 2, 1)]
