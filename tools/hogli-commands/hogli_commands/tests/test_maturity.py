from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.isolation import FacadeClassImport, IsolationStatus, UnapprovedWiringClass
from hogli_commands.product.maturity import _count_tach_depends_on, _isolated_tests_state, _seal_token, score_facade
from hogli_commands.product.wiring_interfaces import WiringVerdict


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


class TestSealState:
    @pytest.mark.parametrize(
        "facade_leaks, unapproved_wiring, expected_token, expected_state",
        [
            ((), (), "ready", "READY"),
            ((FacadeClassImport("models.py", "Thing", "backend/models.py"),), (), "cls:1", "BLOCKED"),
            (
                (),
                (UnapprovedWiringClass("tasks.py", "Job", "backend/tasks.py", WiringVerdict.UNAPPROVED),),
                "cls:1",
                "BLOCKED",
            ),
        ],
        ids=["clean_facade", "facade_hands_out_model", "unapproved_wiring_class"],
    )
    def test_sealed_product_is_ready_only_without_blocking_classes(
        self,
        facade_leaks: tuple[FacadeClassImport, ...],
        unapproved_wiring: tuple[UnapprovedWiringClass, ...],
        expected_token: str,
        expected_state: str,
    ) -> None:
        status = IsolationStatus(
            name="demo",
            has_facade_contracts=True,
            has_real_facade=True,
            has_tach_interface=True,
            has_legacy_leaks=False,
            bypass_entries=(),
            has_contract_check_script=False,
            has_narrowed_turbo=False,
            facade_leaks=facade_leaks,
            unapproved_wiring=unapproved_wiring,
        )

        assert _seal_token(status) == expected_token
        assert _isolated_tests_state(status)[0] == expected_state
