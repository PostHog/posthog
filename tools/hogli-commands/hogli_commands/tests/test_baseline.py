from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.product.baseline import baseline_issues
from hogli_commands.product.paths import is_backend_product_dir


class TestIsolationBaseline:
    @pytest.mark.parametrize(
        "unsealed,baseline,expected",
        [
            pytest.param({"alerts"}, {"alerts"}, 0, id="in_sync"),
            pytest.param({"alerts", "canvas"}, {"alerts"}, 1, id="unsealed_missing_from_baseline"),
            pytest.param({"alerts"}, {"alerts", "wizard"}, 1, id="baseline_entry_now_sealed"),
            pytest.param({"canvas"}, {"wizard"}, 2, id="drift_in_both_directions"),
            pytest.param(set(), set(), 0, id="empty_both"),
        ],
    )
    def test_strict_equality(self, unsealed: set[str], baseline: set[str], expected: int) -> None:
        assert len(baseline_issues(unsealed, baseline)) == expected

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
