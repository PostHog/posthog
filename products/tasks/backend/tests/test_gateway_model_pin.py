import pytest
from unittest.mock import patch

from products.tasks.backend.facade.model_catalogue import available_model_choices
from products.tasks.backend.logic.services.gateway_model_pin import (
    MAX_GATEWAY_PIN_LENGTH,
    FamilyModels,
    family_models,
    gateway_pin,
    model_allowed_by_product_pin,
    offered_listing,
    pinned_run_allows_model,
    product_pin,
)
from products.tasks.backend.logic.services.gateway_models import GatewayModel
from products.tasks.backend.logic.services.model_catalogue import family_model_choices, served_runtime_adapter_for

_PIN_LISTING = "products.tasks.backend.logic.services.gateway_model_pin.list_gateway_models"
_CATALOGUE_LISTING = "products.tasks.backend.logic.services.model_catalogue.list_gateway_models"


def _listed(model_id: str, family: str = "gpt-sol", release_date: str = "") -> GatewayModel:
    return GatewayModel(
        id=model_id, owned_by="openai", context_window=1050000, family=family, release_date=release_date
    )


_CATALOGED = _listed("gpt-6.2-sol", release_date="2026-11-17")
_V3 = _listed("gpt-6.3-sol", release_date="2027-01-10")
_V4 = _listed("gpt-6.4-sol", release_date="2027-03-01")
_V5 = _listed("gpt-6.5-sol", release_date="2027-05-01")


@pytest.mark.parametrize(
    "product,listing,expected",
    [
        pytest.param(
            "posthog_code",
            (_CATALOGED, _V3),
            FamilyModels(admitted=("gpt-6.3-sol",), offered=frozenset({"gpt-6.3-sol"})),
            id="new_version_of_an_allowed_family",
        ),
        pytest.param(
            "posthog_code",
            (_CATALOGED, _V3, _V4, _V5),
            FamilyModels(
                admitted=("gpt-6.5-sol", "gpt-6.4-sol", "gpt-6.3-sol"),
                offered=frozenset({"gpt-6.5-sol", "gpt-6.4-sol"}),
            ),
            id="older_versions_stay_callable_but_leave_the_picker",
        ),
        pytest.param(
            "posthog_code",
            (
                _CATALOGED,
                _listed("gpt-6.1-sol", release_date="2026-09-29"),
                _listed("gpt-5.7-sol", release_date="2026-08-01"),
            ),
            FamilyModels(admitted=("gpt-5.7-sol",), offered=frozenset()),
            id="cataloged_versions_count_toward_the_newest",
        ),
        pytest.param(
            "posthog_code",
            (_listed("gpt-6.3-sol"), _listed("gpt-6.4-sol"), _listed("gpt-6.5-sol")),
            FamilyModels(
                admitted=("gpt-6.3-sol", "gpt-6.4-sol", "gpt-6.5-sol"),
                offered=frozenset({"gpt-6.3-sol", "gpt-6.4-sol", "gpt-6.5-sol"}),
            ),
            id="no_release_dates_offers_every_version",
        ),
        pytest.param(
            "posthog_code",
            (_V3, _V4, _listed("gpt-6.5-sol")),
            FamilyModels(
                admitted=("gpt-6.4-sol", "gpt-6.3-sol", "gpt-6.5-sol"),
                offered=frozenset({"gpt-6.3-sol", "gpt-6.4-sol", "gpt-6.5-sol"}),
            ),
            id="one_missing_release_date_offers_every_version",
        ),
        pytest.param(
            "posthog_code",
            (_listed("gpt-6.3-terra", family="gpt-terra", release_date="2027-01-10"),),
            FamilyModels(),
            id="family_the_product_does_not_allow",
        ),
        pytest.param(
            "posthog_code",
            (_listed("gpt-6.3-sol-law", family="", release_date="2027-01-10"),),
            FamilyModels(),
            id="model_with_no_family",
        ),
        pytest.param(
            "posthog_code",
            (
                _listed("openai/gpt-6.3-sol", release_date="2027-01-10"),
                _listed("GPT-6.3-Sol", release_date="2027-01-10"),
            ),
            FamilyModels(admitted=("gpt-6.3-sol",), offered=frozenset({"gpt-6.3-sol"})),
            id="two_spellings_of_one_model_admit_once",
        ),
        pytest.param("onboarding", (_V3,), FamilyModels(), id="product_with_no_families"),
        pytest.param("signals_scout", (_V3,), FamilyModels(), id="product_with_no_pin"),
    ],
)
def test_family_rule(product: str, listing: tuple[GatewayModel, ...], expected: FamilyModels) -> None:
    assert family_models(product, listing) == expected


@pytest.mark.parametrize(
    "product,listed_id,admitted",
    [
        ("review_hog", "gpt-6.3-sol", ("gpt-6.3-sol",)),
        ("slack_app", "gpt-6.3-sol", ()),
        ("slack_app", "openai/GPT-6.3-Sol", ()),
    ],
    ids=["reserved_for_this_product", "reserved_for_another_product", "reserved_under_another_spelling"],
)
def test_a_reservation_holds_for_every_spelling_of_the_model(
    product: str, listed_id: str, admitted: tuple[str, ...]
) -> None:
    listing = (_listed(listed_id, release_date="2027-01-10"),)
    with patch.dict(
        "products.tasks.backend.logic.services.gateway_model_pin._GATEWAY_RESTRICTED_MODEL_PRODUCTS",
        {"gpt-6.3-sol": frozenset({"review_hog"})},
    ):
        assert family_models(product, listing).admitted == admitted


@pytest.mark.parametrize(
    "state,model,allowed",
    [
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "gpt-6.3-sol", True),
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "openai/gpt-6.3-sol", True),
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "gpt-6.4-sol", False),
        ({"ai_gateway_product": "slack_app"}, "gpt-6.4-sol", False),
        ({"ai_gateway_product": "slack_app"}, "gpt-6.2-sol", True),
        ({}, "gpt-6.4-sol", True),
    ],
    ids=[
        "version_the_token_was_minted_with",
        "provider_qualified_spelling",
        "version_listed_after_the_mint",
        "run_minted_before_any_family_version",
        "catalog_model",
        "unpinned_run",
    ],
)
def test_a_live_run_keeps_to_the_models_its_token_was_minted_with(
    state: dict[str, object], model: str, allowed: bool
) -> None:
    with patch(_PIN_LISTING, return_value=(_V3, _V4)):
        assert pinned_run_allows_model(state, model) is allowed


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-6.2-sol", "codex"),
        ("gpt-6.3-sol", "codex"),
        ("openai/gpt-6.3-sol", "codex"),
        ("gemini-4-neon", None),
        ("gpt-9-unlisted", None),
        (None, None),
    ],
    ids=[
        "catalog_model",
        "listed_model",
        "provider_qualified_spelling",
        "listed_under_a_provider_with_no_runtime",
        "unlisted_model",
        "no_model",
    ],
)
def test_runtime_comes_from_the_catalog_then_the_cached_listing(model: str | None, expected: str | None) -> None:
    listing = (_V3, GatewayModel(id="gemini-4-neon", owned_by="google", context_window=1000000, family="gemini"))
    with patch("products.tasks.backend.logic.services.model_catalogue.cached_gateway_models", return_value=listing):
        assert served_runtime_adapter_for(model) == expected


@pytest.mark.parametrize(
    "offered_only,expected",
    [(True, ["gpt-6.4-sol", "gpt-6.5-sol"]), (False, ["gpt-6.3-sol", "gpt-6.4-sol", "gpt-6.5-sol"])],
    ids=["versions_a_picker_offers", "every_version_a_run_may_call"],
)
def test_family_choices_carry_each_version_once_with_its_runtime(offered_only: bool, expected: list[str]) -> None:
    listing = (_CATALOGED, _V3, _listed("openai/gpt-6.3-sol", release_date="2027-01-10"), _V4, _V5)
    with patch("products.tasks.backend.logic.services.model_catalogue.cached_gateway_models", return_value=listing):
        choices = family_model_choices("slack_app", offered_only=offered_only)

    assert [(choice.model, choice.runtime_adapter) for choice in choices] == [(model, "codex") for model in expected]


def test_a_product_with_no_pin_is_offered_the_whole_listing() -> None:
    listing = (_V3, _listed("gpt-4o", family="gpt"))
    assert offered_listing("signals_scout", listing) == listing


def test_family_models_never_push_the_pin_past_the_gateway_limit() -> None:
    listing = tuple(_listed(f"gpt-7.{minor}-sol", release_date=f"2027-01-{minor + 1:02d}") for minor in range(30))
    listing += tuple(_listed(f"gpt-8.{minor}-sol", release_date=f"2028-01-{minor + 1:02d}") for minor in range(30))

    with patch(_PIN_LISTING, return_value=listing):
        pin = product_pin("posthog_code")

    assert pin is not None
    assert len(gateway_pin(pin)) == MAX_GATEWAY_PIN_LENGTH
    assert "gpt-8.29-sol" in pin
    assert "gpt-7.0-sol" not in pin


@pytest.mark.parametrize(
    "product,model,allowed",
    [
        ("posthog_code", "gpt-6.5-sol", True),
        ("posthog_code", "openai/gpt-6.5-sol", True),
        ("posthog_code", "gpt-6.3-sol", True),
        ("posthog_code", "gpt-4o", False),
        ("slack_app", "gpt-6.5-sol", True),
        ("onboarding", "gpt-6.5-sol", False),
        ("slack_app", "zai-org/glm-5.3", False),
    ],
    ids=[
        "newest_family_version",
        "provider_qualified_spelling",
        "aged_out_family_version",
        "model_outside_every_allowed_family",
        "another_product_with_the_family",
        "product_with_a_fixed_list",
        "cataloged_model_reserved_for_other_products",
    ],
)
def test_pin_admits_family_versions(product: str, model: str, allowed: bool) -> None:
    listing = (_CATALOGED, _V3, _V4, _V5, _listed("gpt-4o", family="gpt"), _listed("zai-org/glm-5.3", family="glm"))
    with patch(_PIN_LISTING, return_value=listing):
        assert model_allowed_by_product_pin(product, model) is allowed


def test_model_list_offers_only_the_newest_family_versions() -> None:
    with patch(_CATALOGUE_LISTING, return_value=(_CATALOGED, _V3, _V4, _V5)):
        offered = [choice.model for choice in available_model_choices("posthog_code")]

    assert offered == ["gpt-6.2-sol", "gpt-6.4-sol", "gpt-6.5-sol"]
