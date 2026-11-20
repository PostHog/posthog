import pytest

from syrupy.extensions.json import JSONSnapshotExtension

from products.tasks.backend.facade.model_catalogue import available_model_choices, product_model_choices
from products.tasks.backend.facade.model_listing_testing import saved_gateway_listing, serve_gateway_listing
from products.tasks.backend.logic.services.gateway_model_pin import (
    MAX_GATEWAY_PIN_LENGTH,
    PRODUCT_ALLOWED_MODELS,
    FamilyModels,
    family_models,
    gateway_pin,
    model_allowed_by_product_pin,
    offered_listing,
    pinned_run_allows_model,
    product_pin,
)
from products.tasks.backend.logic.services.gateway_models import GatewayModel


def _listed(model_id: str, family: str = "gpt-sol", release_date: str = "") -> GatewayModel:
    return GatewayModel(
        id=model_id,
        owned_by="openai",
        context_window=1050000,
        family=family,
        release_date=release_date,
        api_shapes=("openai-chat-completions", "openai-responses"),
    )


_V2 = _listed("gpt-6.2-sol", release_date="2026-11-17")
_V3 = _listed("gpt-6.3-sol", release_date="2027-01-10")
_V4 = _listed("gpt-6.4-sol", release_date="2027-03-01")
_V5 = _listed("gpt-6.5-sol", release_date="2027-05-01")
_DEEPSEEK = _listed("deepseek-ai/deepseek-v4-flash-0731", family="")
_TERRA_TRIAL = _listed("gpt-6.1-terra", family="gpt-terra", release_date="2026-09-29")
_TERRA = _listed("gpt-5.6-terra", family="gpt-terra", release_date="2026-06-01")


@pytest.mark.parametrize(
    "product,listing,expected",
    [
        pytest.param(
            "posthog_code",
            (_V3,),
            FamilyModels(admitted=("gpt-6.3-sol",), offered=frozenset({"gpt-6.3-sol"})),
            id="version_of_an_allowed_family",
        ),
        pytest.param(
            "posthog_code",
            (_V2, _V3, _V4, _V5),
            FamilyModels(
                admitted=("gpt-6.5-sol", "gpt-6.4-sol", "gpt-6.3-sol", "gpt-6.2-sol"),
                offered=frozenset({"gpt-6.5-sol", "gpt-6.4-sol"}),
            ),
            id="older_versions_stay_callable_but_leave_the_picker",
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
            "slack_app",
            (_listed("zai-org/glm-5.3", family="glm", release_date="2026-10-01"),),
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
            (_DEEPSEEK,),
            FamilyModels(admitted=(_DEEPSEEK.id,), offered=frozenset({_DEEPSEEK.id})),
            id="model_with_no_family_the_product_names",
        ),
        pytest.param("slack_app", (_DEEPSEEK,), FamilyModels(), id="model_with_no_family_another_product_names"),
        pytest.param(
            "posthog_code",
            (
                _listed("openai/gpt-6.3-sol", release_date="2027-01-10"),
                _listed("GPT-6.3-Sol", release_date="2027-01-10"),
            ),
            FamilyModels(admitted=("gpt-6.3-sol",), offered=frozenset({"gpt-6.3-sol"})),
            id="two_spellings_of_one_model_admit_once",
        ),
        pytest.param(
            "slack_app",
            (
                _listed("claude-sonnet-5", family="claude-sonnet", release_date="2026-05-01"),
                _listed("claude-sonnet-4-5", family="claude-sonnet", release_date="2025-09-29"),
            ),
            FamilyModels(admitted=("claude-sonnet-5",), offered=frozenset({"claude-sonnet-5"})),
            id="sdk_model_is_already_pinned_and_never_offered",
        ),
        pytest.param(
            "review_hog",
            (_TERRA_TRIAL, _TERRA),
            FamilyModels(admitted=("gpt-6.1-terra", "gpt-5.6-terra"), offered=frozenset({"gpt-5.6-terra"})),
            id="reserved_model_is_callable_by_its_product_and_not_offered",
        ),
        pytest.param(
            "slack_app",
            (_TERRA_TRIAL, _TERRA),
            FamilyModels(admitted=("gpt-5.6-terra",), offered=frozenset({"gpt-5.6-terra"})),
            id="reserved_model_is_withheld_from_another_product",
        ),
        pytest.param(
            "slack_app",
            (_listed("openai/GPT-6.1-Terra", family="gpt-terra", release_date="2026-09-29"),),
            FamilyModels(),
            id="reservation_holds_for_another_spelling",
        ),
        pytest.param("onboarding", (_V3,), FamilyModels(), id="product_with_no_families"),
        pytest.param("signals_scout", (_V3,), FamilyModels(), id="product_with_no_pin"),
    ],
)
def test_family_rule(product: str, listing: tuple[GatewayModel, ...], expected: FamilyModels) -> None:
    assert family_models(product, listing) == expected


@pytest.mark.parametrize(
    "state,model,allowed",
    [
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "gpt-6.3-sol", True),
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "openai/gpt-6.3-sol", True),
        ({"ai_gateway_product": "slack_app", "ai_gateway_family_models": ["gpt-6.3-sol"]}, "gpt-6.4-sol", False),
        ({"ai_gateway_product": "slack_app"}, "gpt-6.4-sol", True),
        ({"ai_gateway_product": "slack_app"}, "gpt-6.9-sol", False),
        ({"ai_gateway_product": "slack_app"}, "claude-haiku-4-5", True),
        ({}, "gpt-6.4-sol", True),
    ],
    ids=[
        "version_the_token_was_minted_with",
        "provider_qualified_spelling",
        "version_listed_after_the_mint",
        "run_with_no_version_stamp_follows_the_listing",
        "run_with_no_version_stamp_and_an_unlisted_model",
        "sdk_model",
        "unpinned_run",
    ],
)
def test_a_live_run_keeps_to_the_models_its_token_was_minted_with(
    state: dict[str, object], model: str, allowed: bool
) -> None:
    with serve_gateway_listing((_V3, _V4)):
        assert pinned_run_allows_model(state, model) is allowed


@pytest.mark.parametrize(
    "product,expected",
    [
        pytest.param("signals_scout", ["gpt-6.3-sol", "claude-sonnet-5", "gpt-4o"], id="product_with_no_pin"),
        pytest.param("onboarding", ["claude-sonnet-5"], id="product_with_a_fixed_list"),
        pytest.param("slack_app", ["gpt-6.3-sol", "claude-sonnet-5"], id="product_with_families"),
    ],
)
def test_what_a_product_is_offered(product: str, expected: list[str]) -> None:
    listing = (_V3, _listed("claude-sonnet-5", family="claude-sonnet"), _listed("gpt-4o", family="gpt-omni"))
    assert [listed.id for listed in offered_listing(product, listing)] == expected


def test_family_models_never_push_the_pin_past_the_gateway_limit() -> None:
    listing = tuple(_listed(f"gpt-7.{minor}-sol", release_date=f"2027-01-{minor + 1:02d}") for minor in range(30))
    listing += tuple(_listed(f"gpt-8.{minor}-sol", release_date=f"2028-01-{minor + 1:02d}") for minor in range(30))
    listing += tuple(_listed(f"gpt-9.{minor}-sol", release_date=f"2029-01-{minor + 1:02d}") for minor in range(10))

    with serve_gateway_listing(listing):
        pin = product_pin("posthog_code")

    assert pin is not None
    assert len(gateway_pin(pin)) == MAX_GATEWAY_PIN_LENGTH
    assert "gpt-9.9-sol" in pin
    assert "gpt-7.0-sol" not in pin


@pytest.mark.parametrize(
    "product,model,allowed",
    [
        ("posthog_code", "gpt-6.5-sol", True),
        ("posthog_code", "openai/gpt-6.5-sol", True),
        ("posthog_code", "gpt-6.2-sol", True),
        ("posthog_code", "o3", False),
        ("posthog_code", "gpt-6.6-sol", False),
        ("slack_app", "gpt-6.5-sol", True),
        ("slack_app", "claude-haiku-4-5", True),
        ("onboarding", "gpt-6.5-sol", False),
        ("slack_app", "zai-org/glm-5.3", False),
        ("posthog_code", "zai-org/glm-5.3", True),
    ],
    ids=[
        "newest_family_version",
        "provider_qualified_spelling",
        "aged_out_family_version",
        "model_outside_every_allowed_family",
        "model_the_gateway_does_not_list",
        "another_product_with_the_family",
        "sdk_model",
        "product_with_a_fixed_list",
        "hosted_family_the_product_does_not_allow",
        "hosted_family_the_product_allows",
    ],
)
def test_pin_admits_family_versions(product: str, model: str, allowed: bool) -> None:
    listing = (_V2, _V3, _V4, _V5, _listed("o3", family="o"), _listed("zai-org/glm-5.3", family="glm"))
    with serve_gateway_listing(listing):
        assert model_allowed_by_product_pin(product, model) is allowed


def test_model_list_offers_only_the_newest_family_versions() -> None:
    with serve_gateway_listing((_V2, _V3, _V4, _V5)):
        offered = [choice.model for choice in available_model_choices("posthog_code")]

    assert offered == ["gpt-6.4-sol", "gpt-6.5-sol"]


@pytest.mark.parametrize(
    "offered_only,expected",
    [
        pytest.param(True, ["gpt-6.4-sol", "gpt-6.5-sol"], id="offered"),
        pytest.param(False, ["gpt-6.2-sol", "gpt-6.3-sol", "gpt-6.4-sol", "gpt-6.5-sol"], id="callable"),
    ],
)
def test_a_product_is_offered_fewer_models_than_it_may_call(offered_only: bool, expected: list[str]) -> None:
    with serve_gateway_listing((_V2, _V3, _V4, _V5)):
        choices = product_model_choices("slack_app", offered_only=offered_only)

    assert [choice.model for choice in choices] == expected


def test_what_each_product_may_call_and_offer_from_the_saved_listing(snapshot) -> None:
    listing = saved_gateway_listing()
    recorded = {
        product: {
            "callable": product_pin(product),
            "offered": [listed.id for listed in offered_listing(product, listing)],
        }
        for product in sorted(PRODUCT_ALLOWED_MODELS)
    }
    assert recorded == snapshot(extension_class=JSONSnapshotExtension)
