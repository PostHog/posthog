from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from posthog.llm.system_one import NoulAnswer, SystemOneNotConfigured, SystemOneResult
from posthog.llm.system_one_client import GatewaySystemOneClient

from products.today.backend.logic.jev import GatewayJev

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCAL_CACHE)
class TestGatewayJev(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_asks_the_model_once_for_each_distinct_text(self) -> None:
        client = MagicMock(spec=GatewaySystemOneClient)
        client.adecide = AsyncMock(
            side_effect=lambda state, questions: SystemOneResult(
                model="jev", answers={"row_0": NoulAnswer(probability=0.8)}, input_tokens=1
            )
        )
        with patch("products.today.backend.logic.jev.build_system_one_client", return_value=client):
            jev = GatewayJev(team_id=1, distinct_id="person")
            first = jev.yes(["cart", "spinner", "cart"], "Is it broken?")
            second = jev.yes(["spinner", "cart"], "Is it broken?")
            other_team = GatewayJev(team_id=2, distinct_id="person").yes(["cart"], "Is it broken?")

        assert (first, second, other_team) == ([0.8, 0.8, 0.8], [0.8, 0.8], [0.8])
        assert client.adecide.await_count == 3

    def test_answers_from_the_cache_without_a_gateway(self) -> None:
        client = MagicMock(spec=GatewaySystemOneClient)
        client.adecide = AsyncMock(
            return_value=SystemOneResult(model="jev", answers={"row_0": NoulAnswer(probability=0.8)}, input_tokens=1)
        )
        with patch("products.today.backend.logic.jev.build_system_one_client", return_value=client):
            GatewayJev(team_id=1, distinct_id="person").yes(["cart"], "Is it broken?")
        with patch(
            "products.today.backend.logic.jev.build_system_one_client", side_effect=SystemOneNotConfigured("no gateway")
        ):
            assert GatewayJev(team_id=1, distinct_id="person").yes(["cart"], "Is it broken?") == [0.8]
