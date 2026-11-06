from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import yaml
from hogli_commands.product.crossings import grown_debt
from hogli_commands.product.ledger_growth import LEDGER_BASE_ENV, SCANNER_DIR, ledger_growth_issues
from hogli_commands.product.paths import REPO_ROOT
from parameterized import parameterized

LEDGER = "products/model_crossing_uses_baseline.txt"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _commit(repo: Path, files: dict[str, str]) -> str:
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(repo, "add", relative)
    _git(repo, "commit", "-m", "change")
    return _git(repo, "rev-parse", "HEAD").strip()


class TestGrownDebt:
    @parameterized.expand(
        [
            (
                "split_consumer",
                ["products.a.X posthog.api.old write 2"],
                ["products.a.X posthog.api.one write 1", "products.a.X posthog.api.two write 1"],
                [],
            ),
            (
                "new_consumer",
                ["products.a.X posthog.api.old write 1"],
                ["products.a.X posthog.api.old write 1", "products.a.X posthog.api.new write 1"],
                ["products.a.X write: 1 → 2"],
            ),
            (
                "new_kind",
                ["products.a.X posthog.api.old write 1"],
                ["products.a.X posthog.api.old write 1", "products.a.X posthog.api.old get_model 1"],
                ["products.a.X get_model: 0 → 1"],
            ),
        ]
    )
    def test_debt_counts_per_crossing_and_kind(
        self, _name: str, base: list[str], current: list[str], expected: list[str]
    ) -> None:
        assert grown_debt(base, current) == expected


class TestLedgerGrowthIssues:
    @pytest.mark.parametrize("touch_scanner, expected_issues", [(False, 1), (True, 0)])
    def test_only_a_scanner_change_may_grow_the_ledger(
        self, touch_scanner: bool, expected_issues: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git(tmp_path, "init", "-q", "-b", "master")
        line = "products.a.X posthog.api.old write 1\n"
        base = _commit(tmp_path, {LEDGER: line, f"{SCANNER_DIR}scan.py": "RULES = 1\n"})
        _git(tmp_path, "checkout", "-q", "-b", "feature")
        head_files = {LEDGER: line + "products.a.X posthog.api.new write 1\n"}
        if touch_scanner:
            head_files[f"{SCANNER_DIR}scan.py"] = "RULES = 2\n"
        _commit(tmp_path, head_files)
        monkeypatch.setenv(LEDGER_BASE_ENV, base)

        issues = ledger_growth_issues(tmp_path, tmp_path / LEDGER)

        assert issues is not None
        assert len(issues) == expected_issues

    def test_a_change_that_may_grow_the_ledger_always_gets_a_human_review(self) -> None:
        policy = yaml.safe_load((REPO_ROOT / ".stamphog" / "policy.yml").read_text())
        guardrails = policy["deny"]["devex_guardrails"]["match"]["paths"]
        assert any(re.match(pattern, f"{SCANNER_DIR}a_new_module.py") for pattern in guardrails)
