from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli_commands.product.baseline import baseline_issues, claims_isolated_level
from hogli_commands.product.paths import is_backend_product_dir

ROOT_TURBO = {"tasks": {"backend:contract-check": {"inputs": ["backend/**/*.py"]}}}


def _product(tmp_path: Path, *, script: bool = True, turbo: dict | None = None) -> Path:
    product = tmp_path / "products" / "my_product"
    product.mkdir(parents=True)
    scripts = {"backend:contract-check": "echo ok"} if script else {}
    (product / "package.json").write_text(json.dumps({"name": "@posthog/products-my-product", "scripts": scripts}))
    if turbo is not None:
        (product / "turbo.json").write_text(json.dumps(turbo))
    (tmp_path / "turbo.json").write_text(json.dumps(ROOT_TURBO))
    return product


def _task(inputs: list[str] | None = None, *, extends: bool = True) -> dict:
    task = {} if inputs is None else {"inputs": inputs}
    return {**({"extends": ["//"]} if extends else {}), "tasks": {"backend:contract-check": task}}


class TestIsolationBaseline:
    @pytest.mark.parametrize(
        "unclaimed,baseline,expected",
        [
            pytest.param({"alerts"}, {"alerts"}, 0, id="in_sync"),
            pytest.param({"alerts", "canvas"}, {"alerts"}, 1, id="unclaimed_missing_from_baseline"),
            pytest.param({"alerts"}, {"alerts", "wizard"}, 1, id="baseline_entry_now_claims"),
            pytest.param({"canvas"}, {"wizard"}, 2, id="drift_in_both_directions"),
            pytest.param(set(), set(), 0, id="empty_both"),
        ],
    )
    def test_strict_equality(self, unclaimed: set[str], baseline: set[str], expected: int) -> None:
        assert len(baseline_issues(unclaimed, baseline)) == expected

    # Read as hoglint's turbo adapter reads a claim, so the baseline and `hoglint check` agree on
    # which products claim the Isolated level.
    @pytest.mark.parametrize(
        "script,turbo,expected",
        [
            pytest.param(True, _task(["backend/facade/**"]), True, id="own_narrowed_inputs"),
            pytest.param(True, None, False, id="no_package_turbo_json"),
            pytest.param(True, _task(), False, id="own_entry_without_inputs_inherits_the_root"),
            pytest.param(True, _task(["$TURBO_DEFAULT$", "x/**"]), False, id="default_marker_watches_everything"),
            pytest.param(True, _task(["$TURBO_EXTENDS$", "x/**"]), True, id="extends_the_narrow_root_inputs"),
            pytest.param(True, _task(extends=False), False, id="no_extends_and_no_inputs_is_the_default"),
            pytest.param(False, _task(["backend/facade/**"]), False, id="no_contract_check_script"),
        ],
    )
    def test_claim_reading(self, tmp_path: Path, script: bool, turbo: dict | None, expected: bool) -> None:
        product = _product(tmp_path, script=script, turbo=turbo)
        assert claims_isolated_level(product, tmp_path / "turbo.json") is expected

    @pytest.mark.parametrize(
        "with_python,expected",
        [
            pytest.param(True, True, id="with_python"),
            pytest.param(False, False, id="empty_leftover_dir"),
        ],
    )
    def test_discovery_requires_python(self, with_python: bool, expected: bool, tmp_path: Path) -> None:
        backend = tmp_path / "some_product" / "backend"
        backend.mkdir(parents=True)
        if with_python:
            (backend / "models.py").write_text("")
        assert is_backend_product_dir(tmp_path / "some_product") is expected

    def test_discovery_skips_products_without_a_backend(self, tmp_path: Path) -> None:
        product = tmp_path / "frontend_only"
        product.mkdir()
        assert is_backend_product_dir(product) is False
