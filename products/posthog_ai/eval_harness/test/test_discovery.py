from __future__ import annotations

from pathlib import Path

import pytest

from products.posthog_ai.eval_harness.harness.discovery import SuiteDiscoveryError, discover_suites
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind

_ONE_SHOT_MODULE = """
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind

SUITE_KIND = SuiteKind.ONE_SHOT


async def eval_alpha(ctx) -> None:
    return None
"""

_DEFAULT_MODULE = """
async def eval_beta(ctx) -> None:
    return None
"""

_SINGULAR_MODULE = """
async def eval_should_be_ignored(ctx) -> None:
    return None
"""


@pytest.fixture
def product_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    products_root = tmp_path / "fakeproducts"
    empty_builtin_root = tmp_path / "builtin"
    empty_builtin_root.mkdir()

    one_shot = products_root / "analytics" / "evals"
    one_shot.mkdir(parents=True)
    (one_shot / "eval_one.py").write_text(_ONE_SHOT_MODULE)

    default = products_root / "core" / "evals"
    default.mkdir(parents=True)
    (default / "eval_two.py").write_text(_DEFAULT_MODULE)

    # Singular ``eval/`` (the existing pytest tree convention) must never be
    # picked up by the harness.
    singular = products_root / "signals" / "eval"
    singular.mkdir(parents=True)
    (singular / "eval_ignored.py").write_text(_SINGULAR_MODULE)

    # The import anchor is the parent of the products root.
    monkeypatch.syspath_prepend(str(tmp_path))
    return products_root, empty_builtin_root


def _discover(product_roots: tuple[Path, Path]) -> dict[str, SuiteKind]:
    products_root, builtin_root = product_roots
    suites = discover_suites(builtin_root=builtin_root, products_root=products_root)
    return {suite.id: suite.kind for suite in suites}


def test_product_suites_discovered_with_product_scoped_ids(product_roots: tuple[Path, Path]) -> None:
    ids = _discover(product_roots)
    assert set(ids) == {"analytics/eval_one::eval_alpha", "core/eval_two::eval_beta"}


def test_singular_eval_dir_is_ignored(product_roots: tuple[Path, Path]) -> None:
    ids = _discover(product_roots)
    assert not any("eval_ignored" in suite_id for suite_id in ids)


@pytest.mark.parametrize(
    "suite_id, expected_kind",
    [
        pytest.param("analytics/eval_one::eval_alpha", SuiteKind.ONE_SHOT, id="marker_respected"),
        pytest.param("core/eval_two::eval_beta", SuiteKind.SANDBOXED, id="absent_marker_defaults_sandboxed"),
    ],
)
def test_suite_kind_resolved_from_product_module(
    product_roots: tuple[Path, Path], suite_id: str, expected_kind: SuiteKind
) -> None:
    assert _discover(product_roots)[suite_id] == expected_kind


def test_selector_matches_product_suite_ids(product_roots: tuple[Path, Path]) -> None:
    products_root, builtin_root = product_roots
    suites = discover_suites(["analytics"], builtin_root=builtin_root, products_root=products_root)
    assert [suite.id for suite in suites] == ["analytics/eval_one::eval_alpha"]


def test_unmatched_selector_raises(product_roots: tuple[Path, Path]) -> None:
    products_root, builtin_root = product_roots
    with pytest.raises(SuiteDiscoveryError):
        discover_suites(["nonexistent"], builtin_root=builtin_root, products_root=products_root)
