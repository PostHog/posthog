import threading
from collections.abc import Callable, Mapping

from unittest.mock import patch

from parameterized import parameterized

from posthog.llm.system_one import (
    JsonValue,
    NoulAnswer,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)

from products.replay_vision.backend.search_rerank import RerankCandidate, rerank


class _FakeClient:
    def __init__(self, probability_by_text: Mapping[str, float], block: threading.Event | None = None) -> None:
        self.probability_by_text = probability_by_text
        self.block = block
        self.seen_texts: list[str] = []

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        if self.block is not None:
            self.block.wait(timeout=5)
        assert isinstance(state, dict)
        observations = state["observations"]
        assert isinstance(observations, dict)
        texts = [str(observations[f"o{i}"]) for i in range(len(questions))]
        self.seen_texts.extend(texts)
        return SystemOneResult(
            model="jev",
            answers={f"q{i}": NoulAnswer(probability=self.probability_by_text[text]) for i, text in enumerate(texts)},
            input_tokens=1,
        )


def _candidates(*specs: tuple[str, float]) -> list[RerankCandidate]:
    return [RerankCandidate(observation_id=text, distance=distance, text=text) for text, distance in specs]


class TestRerank:
    def test_orders_the_head_by_probability_breaks_ties_by_distance_and_keeps_the_tail(self) -> None:
        candidates = _candidates(("a", 0.1), ("b", 0.2), ("c", 0.3), ("d", 0.4), ("tail", 0.5))
        client = _FakeClient({"a": 0.2, "b": 0.9, "c": 0.9, "d": 0.95})

        with (
            patch("products.replay_vision.backend.search_rerank.RERANK_CANDIDATES", 4),
            patch("products.replay_vision.backend.search_rerank.build_system_one_client", return_value=client),
        ):
            outcome = rerank("gave up at checkout", candidates, team_id=1)

        assert outcome.reranked
        assert outcome.order == ["d", "b", "c", "a", "tail"]
        assert sorted(client.seen_texts) == ["a", "b", "c", "d"]

    @parameterized.expand(
        [
            ("not_configured", lambda: SystemOneNotConfigured("no gateway")),
            ("gateway_error", lambda: SystemOneRequestFailed("HTTP 502", status_code=502)),
        ]
    )
    def test_falls_back_to_embedding_order_when_the_model_fails(
        self, _name: str, make_error: Callable[[], Exception]
    ) -> None:
        candidates = _candidates(("a", 0.1), ("b", 0.2), ("c", 0.3))

        with patch("products.replay_vision.backend.search_rerank.build_system_one_client", side_effect=make_error()):
            outcome = rerank("gave up at checkout", candidates, team_id=1)

        assert not outcome.reranked
        assert outcome.order == ["a", "b", "c"]

    def test_falls_back_to_embedding_order_when_the_model_misses_the_deadline(self) -> None:
        candidates = _candidates(("a", 0.1), ("b", 0.2), ("c", 0.3))
        release = threading.Event()
        client = _FakeClient({"a": 0.1, "b": 0.5, "c": 0.9}, block=release)

        try:
            with (
                patch("products.replay_vision.backend.search_rerank.RERANK_DEADLINE_S", 0.05),
                patch("products.replay_vision.backend.search_rerank.build_system_one_client", return_value=client),
            ):
                outcome = rerank("gave up at checkout", candidates, team_id=1)
        finally:
            release.set()

        assert not outcome.reranked
        assert outcome.order == ["a", "b", "c"]
