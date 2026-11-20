from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Final

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from openai.types import Model

from products.tasks.backend.logic.services import gateway_models
from products.tasks.backend.logic.services.gateway_models import (
    GatewayModel,
    cached_gateway_models,
    list_gateway_models,
)

_BUILD_CLIENT = "posthog.llm.gateway_client.build_openai_client"
_PRODUCT: Final = "posthog_code"
_FRESH_KEY = f"{gateway_models._CACHE_KEY_PREFIX}:{_PRODUCT}"
_LAST_GOOD_KEY = f"{gateway_models._LAST_GOOD_CACHE_KEY_PREFIX}:{_PRODUCT}"

_BARE_ROW: dict[str, Any] = {"id": "gpt-6.2-sol", "canonical": "openai/gpt-6.2-sol", "owned_by": "openai"}


def _client(rows: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.with_options.return_value.models.list.return_value = SimpleNamespace(
        data=[Model.construct(**row) for row in rows]
    )
    return client


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    cache.delete_many([_FRESH_KEY, _LAST_GOOD_KEY])
    yield
    cache.delete_many([_FRESH_KEY, _LAST_GOOD_KEY])


@pytest.mark.parametrize(
    "row,expected",
    [
        pytest.param(
            {
                **_BARE_ROW,
                "context_window": 922000,
                "name": "GPT-6.2 Sol",
                "family": "gpt-sol",
                "release_date": "2026-11-17",
                "reasoning": {"efforts": ["low", "medium", "high", "xhigh", "max"], "can_disable": False},
                "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            },
            GatewayModel(
                id="gpt-6.2-sol",
                owned_by="openai",
                context_window=922000,
                name="GPT-6.2 Sol",
                family="gpt-sol",
                release_date="2026-11-17",
                reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
                input_per_mtok=2.0,
                output_per_mtok=10.0,
            ),
            id="every_fact",
        ),
        pytest.param(
            {**_BARE_ROW, "context_window": 922000, "family": "gpt-sol", "pricing": {"prompt": "0.000002"}},
            GatewayModel(
                id="gpt-6.2-sol", owned_by="openai", context_window=922000, family="gpt-sol", input_per_mtok=2.0
            ),
            id="some_facts",
        ),
        pytest.param(
            {**_BARE_ROW, "pricing": {"prompt": "n/a", "completion": "0.00001"}},
            GatewayModel(id="gpt-6.2-sol", owned_by="openai", context_window=0, output_per_mtok=10.0),
            id="unparseable_price",
        ),
        pytest.param(
            {**_BARE_ROW, "reasoning": None},
            GatewayModel(id="gpt-6.2-sol", owned_by="openai", context_window=0),
            id="no_facts",
        ),
        pytest.param(
            {**_BARE_ROW, "reasoning": {"efforts": [], "can_disable": True}},
            GatewayModel(id="gpt-6.2-sol", owned_by="openai", context_window=0, reasoning_efforts=()),
            id="no_effort_control",
        ),
    ],
)
def test_reads_model_facts_from_a_listing_row(row: dict[str, Any], expected: GatewayModel) -> None:
    with patch(_BUILD_CLIENT, return_value=_client([row])):
        assert list_gateway_models(_PRODUCT) == (expected,)


def test_skips_a_model_the_credential_may_not_call() -> None:
    rows = [{**_BARE_ROW, "allowed": False}, {**_BARE_ROW, "id": "gpt-6-luna", "allowed": True}]
    with patch(_BUILD_CLIENT, return_value=_client(rows)):
        assert [model.id for model in list_gateway_models(_PRODUCT)] == ["gpt-6-luna"]


def test_serves_the_cached_listing_without_fetching_again() -> None:
    with patch(_BUILD_CLIENT, return_value=_client([_BARE_ROW])):
        served = list_gateway_models(_PRODUCT)

    with patch(_BUILD_CLIENT, return_value=_client([{**_BARE_ROW, "id": "fetched-again"}])):
        assert list_gateway_models(_PRODUCT) == served


def test_a_cache_that_refuses_writes_does_not_fail_the_listing() -> None:
    with (
        patch(_BUILD_CLIENT, return_value=_client([_BARE_ROW])),
        patch.object(cache, "set", side_effect=RuntimeError("cache down")),
    ):
        assert [model.id for model in list_gateway_models(_PRODUCT)] == ["gpt-6.2-sol"]


def test_serves_the_last_listing_when_the_gateway_fails() -> None:
    with patch(_BUILD_CLIENT, return_value=_client([_BARE_ROW])):
        served = list_gateway_models(_PRODUCT)
    cache.delete(_FRESH_KEY)

    with patch(_BUILD_CLIENT, side_effect=RuntimeError("gateway down")):
        assert list_gateway_models(_PRODUCT) == served


def test_serves_nothing_when_the_gateway_has_never_answered() -> None:
    with patch(_BUILD_CLIENT, side_effect=RuntimeError("gateway down")):
        assert list_gateway_models(_PRODUCT) == ()


@pytest.mark.parametrize(
    "expire_fresh,fetched_before,expected_ids",
    [(False, True, ["gpt-6.2-sol"]), (True, True, ["gpt-6.2-sol"]), (False, False, [])],
    ids=["fresh_listing", "last_listing_after_expiry", "nothing_fetched_yet"],
)
def test_cached_listing_never_calls_the_gateway(
    expire_fresh: bool, fetched_before: bool, expected_ids: list[str]
) -> None:
    if fetched_before:
        with patch(_BUILD_CLIENT, return_value=_client([_BARE_ROW])):
            list_gateway_models(_PRODUCT)
    if expire_fresh:
        cache.delete(_FRESH_KEY)

    with patch(_BUILD_CLIENT, return_value=_client([{**_BARE_ROW, "id": "fetched-on-read"}])):
        assert [model.id for model in cached_gateway_models(_PRODUCT)] == expected_ids


def test_cached_listing_is_empty_when_the_cache_is_down() -> None:
    with patch.object(cache, "get", side_effect=RuntimeError("cache down")):
        assert cached_gateway_models(_PRODUCT) == ()
