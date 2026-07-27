"""Joining external tokens back to a product directory.

Several derivation sources name a product with a token that is not exactly a directory
name: a scout's `metadata.scope`, an agent-mode filename, an `ee/hogai/context/` module.
This module holds the single mechanical join used by all of them, so no source invents
its own matching rules.

The join is deliberately dumb. It normalizes case and separators, consults the shared
alias file, and tries one round of de-pluralization. It never guesses beyond that: a
token that does not resolve is reported as unattributed rather than assigned to the
nearest-looking product.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import MatchKind

# Aliases live at the repo level (not inside this package) because they are a fact about
# product directory naming, shared with services/mcp/scripts/scaffold-yaml.ts.
_ALIASES_FILENAME = "product-aliases.json"


@dataclass(frozen=True)
class Join:
    product: str | None
    match: MatchKind


NO_JOIN = Join(None, "none")


def normalize_token(token: str) -> str:
    """kebab/space -> snake, lowercased. Purely mechanical, no semantics."""
    return token.strip().lower().replace("-", "_").replace(" ", "_")


def load_aliases(products_dir: Path) -> dict[str, str]:
    """Load the shared alias map. Missing file is fatal: silently running with no
    aliases would produce wrong `unattributed` output that looks plausible."""
    path = products_dir / _ALIASES_FILENAME
    data = json.loads(path.read_text())
    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise ValueError(f"{path} must contain an `aliases` object")
    return {normalize_token(k): normalize_token(v) for k, v in aliases.items()}


def _depluralize(token: str) -> str | None:
    """Strip exactly one trailing `s`. Resolves the singular/plural mismatch between
    `ee/hogai/context/survey/` and `products/surveys/`."""
    return token[:-1] if token.endswith("s") and len(token) > 1 else None


def join_to_product(token: str, product_dirs: set[str], aliases: dict[str, str]) -> Join:
    """Resolve an external token to a product directory, recording how confident we are.

    Callers should surface `match` in their facts so a consumer can discount a join that
    relied on normalization rather than an exact name.
    """
    normalized = normalize_token(token)

    # Aliases are consulted before exact matches, deliberately. An alias exists precisely
    # to redirect a token away from the directory it appears to name — `llm_analytics`
    # resolves to `ai_observability` even though `products/llm_analytics` still exists,
    # because that directory is a vestigial shell. Checking exact first would make every
    # such alias dead config and silently attribute facts to the wrong product.
    aliased = aliases.get(normalized)
    if aliased and aliased in product_dirs:
        return Join(aliased, "alias")

    if normalized in product_dirs:
        return Join(normalized, "exact")

    singular = _depluralize(normalized)
    if singular and singular in product_dirs:
        return Join(singular, "normalized")

    plural = f"{normalized}s"
    if plural in product_dirs:
        return Join(plural, "normalized")

    return NO_JOIN


def assert_no_ambiguous_joins(tokens: list[str], product_dirs: set[str], aliases: dict[str, str]) -> None:
    """Fail loudly if de-pluralization is doing more work than it can justify.

    `_depluralize` is a heuristic wearing an algorithm's clothes. It is safe while at
    most one token per product relies on it — the moment two distinct tokens both *fuzzy*
    resolve to the same product, we can no longer tell which one the repo meant, and
    picking either silently attributes facts on a coin flip.

    Exact and alias matches are authoritative and never counted here: a token that
    matches a directory outright is not a guess.
    """
    fuzzy_targets: dict[str, list[str]] = {}
    for token in tokens:
        join = join_to_product(token, product_dirs, aliases)
        if join.product and join.match == "normalized":
            fuzzy_targets.setdefault(join.product, []).append(token)

    collisions = {product: sorted(toks) for product, toks in fuzzy_targets.items() if len(toks) > 1}
    if collisions:
        raise ValueError(
            "ambiguous product joins — de-pluralization maps multiple distinct tokens onto "
            f"the same product: {collisions}. Resolve with an explicit entry in "
            "products/product-aliases.json."
        )
