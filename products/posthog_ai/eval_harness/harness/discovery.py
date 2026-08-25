from __future__ import annotations

import inspect
import logging
import importlib
from collections.abc import Callable, Coroutine, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from .requirements import SuiteKind

if TYPE_CHECKING:
    from .context import EvalContext

logger = logging.getLogger(__name__)

BUILTIN_EVALS_PACKAGE = "products.posthog_ai.evals"
REPO_ROOT = Path(__file__).resolve().parents[4]
BUILTIN_EVALS_ROOT = REPO_ROOT / "products" / "posthog_ai" / "evals"
PRODUCTS_ROOT = REPO_ROOT / "products"

EvalSuiteFn = Callable[["EvalContext"], Coroutine[Any, Any, None]]


class SuiteDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvalSuite:
    domain: str
    """Directory the suite lives in, e.g. ``experiments`` for a sandboxed suite or
    ``<product>`` for a product-owned suite. ``root`` for top-level sandboxed files."""

    module_name: str
    fn_name: str
    fn: EvalSuiteFn

    kind: SuiteKind = SuiteKind.SANDBOXED
    """How the suite's cases execute, from the module-level ``SUITE_KIND``."""

    @property
    def id(self) -> str:
        return f"{self.domain}/{self.module_name}::{self.fn_name}"


def _builtin_modules(root: Path) -> Iterator[tuple[str, str, str]]:
    """Yield ``(domain, module_name, dotted)`` for every ``eval_*.py`` in the
    built-in evals tree. The domain falls out of the directory the file lives in."""
    for path in sorted(root.rglob("eval_*.py")):
        relative = path.relative_to(root)
        domain = relative.parent.as_posix().replace("/", ".") if relative.parent != Path(".") else "root"
        dotted_parent = "" if domain == "root" else f".{domain}"
        yield domain, path.stem, f"{BUILTIN_EVALS_PACKAGE}{dotted_parent}.{path.stem}"


def _product_modules(root: Path, *, exclude_root: Path) -> Iterator[tuple[str, str, str]]:
    """Yield ``(domain, module_name, dotted)`` for every ``eval_*.py`` under a
    ``products/<product>/evals/`` tree (plural ``evals`` — the singular
    ``products/signals/eval/`` pytest tree is deliberately not matched).

    The built-in tree (``exclude_root``) also matches the glob, but its suites keep
    their per-directory domains, so ``_builtin_modules`` owns it and it is skipped here.

    The import anchor is ``root.parent`` (the repo root for the real
    ``products/`` dir), so the dotted path is ``<root name>.<product>.evals.…`` —
    ``products.<product>.evals.<module>`` in production."""
    for path in sorted(root.glob("*/evals/**/eval_*.py")):
        if path.resolve().is_relative_to(exclude_root.resolve()):
            continue
        relative = path.relative_to(root)
        product = relative.parts[0]
        dotted = ".".join([root.name, *relative.with_suffix("").parts])
        yield product, path.stem, dotted


def _import_suite_module(dotted: str, module_target: str, selectors: Sequence[str]) -> ModuleType | None:
    """Import a discovered module, applying the shared import-failure policy.

    A selected run only cares about the modules its selectors target, so a broken
    *unrelated* module is skipped. A no-selector run (full run or ``--list``) is
    the repo's import smoke check, so there a failure stays fatal.

    Selectors are matched against ``<domain>/<module>`` (not the full
    ``<domain>/<module>::<fn>`` suite id): a module that failed to import has no
    function names to build ids from, so a ``::fn``-style selector can't match here
    and the module is treated as unrelated — acceptable, since such a selector
    still fails the run loudly via the "No eval suites matched" check.
    """
    try:
        return importlib.import_module(dotted)
    except Exception as e:
        if selectors and not any(selector in module_target for selector in selectors):
            logger.warning("Skipping unselected eval module %s that failed to import: %s", dotted, e)
            return None
        raise SuiteDiscoveryError(f"Failed to import eval module {dotted}: {e}") from e


def _collect_suites(module: ModuleType, domain: str, module_name: str, dotted: str) -> list[EvalSuite]:
    kind = getattr(module, "SUITE_KIND", SuiteKind.SANDBOXED)
    if not isinstance(kind, SuiteKind):
        raise SuiteDiscoveryError(f"{dotted}.SUITE_KIND must be a SuiteKind member, got {kind!r}")
    collected: list[EvalSuite] = []
    for fn_name, fn in vars(module).items():
        if not fn_name.startswith("eval_") or not inspect.iscoroutinefunction(fn):
            continue
        # Only functions defined here — an `eval_*` imported from a sibling
        # module would otherwise be collected twice.
        if fn.__module__ != dotted:
            continue
        collected.append(EvalSuite(domain=domain, module_name=module_name, fn_name=fn_name, fn=fn, kind=kind))
    return collected


def discover_suites(
    selectors: Sequence[str] = (),
    *,
    builtin_root: Path = BUILTIN_EVALS_ROOT,
    products_root: Path = PRODUCTS_ROOT,
) -> list[EvalSuite]:
    """Import every ``eval_*.py`` under the built-in evals tree and the
    ``products/*/evals/`` trees, and collect their ``eval_*`` coroutines.

    Convention over registry: a new eval file is picked up with no boilerplate,
    and its domain falls out of the directory it lives in. Roots are injectable so
    discovery can be exercised against a fixture tree in tests.
    """
    modules: list[tuple[str, str, str]] = [
        *_builtin_modules(builtin_root),
        *_product_modules(products_root, exclude_root=builtin_root),
    ]

    suites: list[EvalSuite] = []
    for domain, module_name, dotted in modules:
        module_target = f"{domain}/{module_name}"
        module = _import_suite_module(dotted, module_target, selectors)
        if module is None:
            continue
        suites.extend(_collect_suites(module, domain, module_name, dotted))

    if not selectors:
        return suites

    selected = [suite for suite in suites if any(selector in suite.id for selector in selectors)]
    if not selected:
        raise SuiteDiscoveryError(
            f"No eval suites matched {list(selectors)}. Run with --list to see the available suite ids."
        )
    return selected
