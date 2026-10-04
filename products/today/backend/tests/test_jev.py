from unittest.mock import AsyncMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from posthog.llm.system_one import NoulAnswer, Question, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult
from posthog.llm.system_one_client import GatewaySystemOneClient

from products.today.backend.logic.jev import GatewayJev

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CLIENT = GatewaySystemOneClient(
    url="https://gateway.example.com", api_key="test-key", headers={}, model="jev", timeout=30
)


def answered(state: dict[str, str], questions: dict[str, Question]) -> SystemOneResult:
    return SystemOneResult(model="jev", answers={key: NoulAnswer(probability=0.8) for key in questions}, input_tokens=1)


@override_settings(CACHES=LOCAL_CACHE)
class TestGatewayJev(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def _ask(self, adecide: AsyncMock, items: list[str], team_id: int = 1) -> list[float | None]:
        with (
            patch("products.today.backend.logic.jev.build_system_one_client", return_value=CLIENT),
            patch.object(GatewaySystemOneClient, "adecide", adecide),
        ):
            return GatewayJev(team_id=team_id, distinct_id="person").yes_probability(items, "Is it broken?")

    def test_asks_the_model_once_for_each_distinct_text(self) -> None:
        adecide = AsyncMock(side_effect=answered)

        first = self._ask(adecide, ["cart", "spinner", "cart"])
        second = self._ask(adecide, ["spinner", "cart"])
        other_team = self._ask(adecide, ["cart"], team_id=2)

        assert (first, second, other_team) == ([0.8, 0.8, 0.8], [0.8, 0.8], [0.8])
        assert [sorted(call.kwargs["state"].values()) for call in adecide.await_args_list] == [
            ["cart", "spinner"],
            ["cart"],
        ]

    def test_keeps_the_answers_of_batches_that_succeed_when_another_fails(self) -> None:
        items = [f"text {index}" for index in range(40)]

        def first_batch_fails(state: dict[str, str], questions: dict[str, Question]) -> SystemOneResult:
            if "text 0" in state.values():
                raise SystemOneRequestFailed("gateway down", status_code=500)
            return answered(state, questions)

        with self.assertRaises(SystemOneRequestFailed):
            self._ask(AsyncMock(side_effect=first_batch_fails), items)
        retry = AsyncMock(side_effect=answered)

        assert self._ask(retry, items) == [0.8] * 40
        assert [len(call.kwargs["state"]) for call in retry.await_args_list] == [32]

    def test_answers_from_the_cache_without_a_gateway(self) -> None:
        self._ask(AsyncMock(side_effect=answered), ["cart"])
        with patch(
            "products.today.backend.logic.jev.build_system_one_client", side_effect=SystemOneNotConfigured("no gateway")
        ):
            assert GatewayJev(team_id=1, distinct_id="person").yes_probability(["cart"], "Is it broken?") == [0.8]
