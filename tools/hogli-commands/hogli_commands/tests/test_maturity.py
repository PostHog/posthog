from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.maturity import _count_tach_depends_on, score_facade


class TestCountTachDependsOn:
    @pytest.mark.parametrize(
        "depends_on, expected",
        [
            ('["posthog", "products.tasks"]', ["products.tasks"]),
            (
                '[\n    "posthog",\n    # why this edge exists\n    "products.tasks",\n    "ee",\n]',
                ["products.tasks"],
            ),
            (
                '[\n    "products.tasks", "products.access_control",\n    "products.cohorts",\n]',
                ["products.tasks", "products.access_control", "products.cohorts"],
            ),
            ('["posthog", "ee"]', []),
        ],
        ids=["single_line", "comment_lines", "several_per_line", "baseline_only"],
    )
    def test_counts_only_real_cross_product_deps(self, depends_on: str, expected: list[str]) -> None:
        block = f'[[modules]]\npath = "products.demo"\ndepends_on = {depends_on}\n'
        assert _count_tach_depends_on(block) == (len(expected), expected)


class TestScoreFacade:
    def test_product_without_logic_module_gets_full_score(self, tmp_path: Path) -> None:
        facade = tmp_path / "facade"
        facade.mkdir()
        (facade / "contracts.py").write_text(
            "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Thing:\n    id: int\n"
        )
        (facade / "api.py").write_text("def list_things(): ...\ndef get_thing(): ...\ndef make_thing(): ...\n")
        presentation = tmp_path / "presentation"
        presentation.mkdir()
        (presentation / "views.py").write_text("from products.demo.backend.facade import api\n")

        assert score_facade(tmp_path).score == 100
