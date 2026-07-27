from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli_commands.product.capabilities import build as cap_build
from hogli_commands.product.capabilities.context import DerivationContext
from hogli_commands.product.capabilities.join import assert_no_ambiguous_joins, join_to_product, normalize_token
from hogli_commands.product.capabilities.models import PROSE_KEYS, SurfaceFact
from hogli_commands.product.capabilities.sources import (
    mcp as mcp_source,
    onboarding as onboarding_source,
    scouts as scouts_source,
)
from pydantic import ValidationError


@pytest.fixture(scope="module")
def spec() -> cap_build.CapabilitySpec:
    return cap_build.build_spec()


@pytest.fixture(scope="module")
def by_product(spec: cap_build.CapabilitySpec) -> dict[str, object]:
    return {p.product: p for p in spec.products}


def _fact(product, dotted: str) -> object:
    group, key, attr = dotted.split(".", 2)
    fact = getattr(product, group)[key]
    return getattr(fact, attr) if attr in {"availability", "unknown_reason"} else fact.facts.get(attr)


# The manual product mapping this spec replaces, encoded as assertions — one entry per
# *derivation rule*, not per product. More products would exercise the same code paths
# with different data: churn without coverage. Negatives and `unknown`s are asserted
# deliberately, since a golden set of only `available` checks would still pass if a bug
# made everything available.
GOLDEN: dict[str, dict[str, object]] = {
    "error_tracking": {
        # The all-positive baseline: if a bug made a whole source return empty, this is
        # the first thing to go red.
        "surfaces.mcp.availability": "available",
        "surfaces.self_driving.availability": "available",
        "data_sources.onboarding_sdks.availability": "available",
        # A deferred surface must stay `unknown`, never silently become a negative.
        "surfaces.cli.availability": "unknown",
    },
    "replay": {
        # Reached only through the `session_replay` alias. If alias resolution regresses
        # to preferring an exact directory match, this product silently loses its scout
        # and its onboarding flow — the exact bug this ordering was written to prevent.
        "surfaces.self_driving.availability": "available",
        "data_sources.onboarding_sdks.availability": "available",
    },
    "llm_analytics": {
        # The other half of that alias: a vestigial shell that must read as empty rather
        # than absorbing the real AI observability product's facts.
        "surfaces.mcp.availability": "unavailable",
        "data_sources.onboarding_sdks.availability": "unavailable",
    },
    # Every enabled tool sits behind the `mcp-analytics` flag, so the surface exists but
    # nobody can reach it without opting in. Guards the preview rule specifically.
    "mcp_analytics": {"surfaces.mcp.availability": "preview"},
}


@pytest.mark.parametrize("product_name", sorted(GOLDEN))
def test_golden_set(by_product: dict, product_name: str) -> None:
    product = by_product[product_name]
    for dotted, expected in GOLDEN[product_name].items():
        assert _fact(product, dotted) == expected, f"{product_name}.{dotted}"


def test_mcp_facts_are_populated_not_just_counted(by_product: dict) -> None:
    # An availability verdict alone would still pass if `facts` came back empty, leaving
    # consumers with a surface they cannot describe. Assert the payload is really there
    # without pinning individual tool names, which get renamed legitimately.
    facts = by_product["error_tracking"].surfaces["mcp"].facts
    assert facts["enabled_tool_count"] == len(facts["tool_names"]) > 0
    assert all(isinstance(name, str) for name in facts["tool_names"])
    assert any(scope.startswith("error_tracking:") for scope in facts["scopes"])


def test_every_product_appears_once_with_full_key_set(spec: cap_build.CapabilitySpec) -> None:
    names = [p.product for p in spec.products]
    assert len(names) == len(set(names))
    for product in spec.products:
        # A missing key is indistinguishable from a negative answer to a consumer.
        assert list(product.surfaces) == cap_build.SURFACE_KEYS
        assert list(product.data_sources) == cap_build.DATA_SOURCE_KEYS


def test_output_carries_no_prose(spec: cap_build.CapabilitySpec) -> None:
    payload = json.loads(cap_build.serialize(spec))

    def walk(node: object) -> set[str]:
        if isinstance(node, dict):
            return {k for k in node if k in PROSE_KEYS} | {f for v in node.values() for f in walk(v)}
        if isinstance(node, list):
            return {f for item in node for f in walk(item)}
        return set()

    assert walk(payload) == set()


def test_release_stamps_only_when_asked(spec: cap_build.CapabilitySpec) -> None:
    assert spec.generated_at is None and spec.commit_sha is None
    released = cap_build.build_spec(release=True)
    assert released.generated_at is not None


def test_unattributed_scout_scopes_do_not_grow_silently(spec: cap_build.CapabilitySpec) -> None:
    # Each orphan keeps 56 products on `unknown` for self_driving. Growth should be a
    # conscious decision, so pin the count and force an explicit bump.
    assert len(spec.unattributed.scout_scopes) <= 11, f"new unattributed scout scopes: {spec.unattributed.scout_scopes}"


def test_self_driving_is_unknown_not_unavailable_while_scopes_are_orphaned(
    spec: cap_build.CapabilitySpec, by_product: dict
) -> None:
    if not spec.unattributed.scout_scopes:
        pytest.skip("scout attribution is complete; the world is closed")
    verdicts = {p.surfaces["self_driving"].availability for p in spec.products}
    assert "unavailable" not in verdicts


# --- honesty contract -------------------------------------------------------------


def test_verdict_requires_a_source_file() -> None:
    with pytest.raises(ValidationError):
        SurfaceFact(availability="available", **{"from": []})


def test_unknown_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        SurfaceFact(availability="unknown")


def test_unknown_reason_is_rejected_on_a_known_verdict() -> None:
    with pytest.raises(ValidationError):
        SurfaceFact(availability="unavailable", unknown_reason="why", **{"from": ["a"]})


# --- join -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [("Error-Tracking", "error_tracking"), ("web analytics", "web_analytics"), ("MCP_Analytics", "mcp_analytics")],
)
def test_normalize_token(token: str, expected: str) -> None:
    assert normalize_token(token) == expected


def test_alias_beats_an_exact_directory_match() -> None:
    # products/llm_analytics exists but is vestigial; the alias must win or the real
    # product silently loses its scout.
    dirs = {"llm_analytics", "ai_observability"}
    join = join_to_product("llm_analytics", dirs, {"llm_analytics": "ai_observability"})
    assert (join.product, join.match) == ("ai_observability", "alias")


@pytest.mark.parametrize("token,expected", [("survey", "surveys"), ("feature_flag", "feature_flags")])
def test_depluralization(token: str, expected: str) -> None:
    join = join_to_product(token, {expected}, {})
    assert (join.product, join.match) == (expected, "normalized")


def test_unjoinable_token_reports_none() -> None:
    assert join_to_product("apm", {"error_tracking"}, {}).product is None


def test_ambiguous_joins_raise() -> None:
    # Both tokens reach `surveys` only by de-pluralization, so neither is authoritative.
    with pytest.raises(ValueError, match="ambiguous product joins"):
        assert_no_ambiguous_joins(["survey", "surveyss"], {"surveys"}, {})


def test_exact_match_alongside_a_fuzzy_one_is_not_ambiguous() -> None:
    # `surveys` matches the directory outright, so it is authoritative and `survey`
    # resolving to the same product is agreement, not a collision.
    assert_no_ambiguous_joins(["survey", "surveys"], {"surveys"}, {})


# --- source units -----------------------------------------------------------------


def _ctx(tmp_path: Path, products: set[str]) -> DerivationContext:
    products_dir = tmp_path / "products"
    for name in products:
        (products_dir / name).mkdir(parents=True, exist_ok=True)
    (products_dir / "product-aliases.json").write_text(json.dumps({"aliases": {}}))
    return DerivationContext(repo_root=tmp_path, products_dir=products_dir, product_dirs=products)


def test_mcp_all_tools_disabled_is_unavailable(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha"})
    tools = ctx.products_dir / "alpha" / "mcp"
    tools.mkdir(parents=True)
    (tools / "tools.yaml").write_text("tools:\n  a-tool:\n    enabled: false\n")
    fact = mcp_source.derive(ctx)["alpha"]
    assert fact.availability == "unavailable"
    assert fact.facts["total_operation_count"] == 1


def test_mcp_all_enabled_tools_flag_gated_is_preview(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha"})
    tools = ctx.products_dir / "alpha" / "mcp"
    tools.mkdir(parents=True)
    (tools / "tools.yaml").write_text("tools:\n  a-tool:\n    enabled: true\n    feature_flag: beta-thing\n")
    assert mcp_source.derive(ctx)["alpha"].availability == "preview"


def test_mcp_returns_a_fact_for_every_product(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha", "beta"})
    assert set(mcp_source.derive(ctx)) == {"alpha", "beta"}


def test_scout_missing_metadata_block_is_tolerated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha"})
    scout = tmp_path / "products" / "signals" / "skills" / "signals-scout-thing"
    scout.mkdir(parents=True)
    (scout / "SKILL.md").write_text("---\nname: signals-scout-thing\ndescription: x\n---\n\nbody\n")
    assert scouts_source.unattributed_scopes(ctx) == []
    assert scouts_source.derive(ctx)["alpha"].availability in {"unknown", "unavailable"}


def test_onboarding_opens_the_world_when_a_directory_does_not_join(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha"})
    orphan = tmp_path / "docs" / "onboarding" / "not-a-product"
    orphan.mkdir(parents=True)
    (orphan / "web.tsx").write_text("")
    fact = onboarding_source.derive(ctx)["alpha"]
    assert fact.availability == "unknown"
    assert onboarding_source.unattributed_dirs(ctx) == ["not-a-product"]


def test_onboarding_closed_world_proves_absence(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"alpha", "beta"})
    flow = tmp_path / "docs" / "onboarding" / "alpha"
    flow.mkdir(parents=True)
    (flow / "web.tsx").write_text("")
    (flow / "index.ts").write_text("")
    results = onboarding_source.derive(ctx)
    assert results["alpha"].availability == "available"
    assert results["alpha"].facts["sdks"] == ["web"]
    assert results["beta"].availability == "unavailable"
