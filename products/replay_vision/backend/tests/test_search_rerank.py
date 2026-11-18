import threading
from collections.abc import Mapping

from unittest.mock import MagicMock, patch

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


def _candidates(*texts: str) -> list[RerankCandidate]:
    return [RerankCandidate(observation_id=text, text=text) for text in texts]


class TestRerank:
    def test_orders_by_probability_and_keeps_embedding_order_on_ties(self) -> None:
        candidates = _candidates("a", "b", "c", "d")
        client = _FakeClient({"a": 0.2, "b": 0.9, "c": 0.9, "d": 0.95})

        with patch("products.replay_vision.backend.search_rerank.build_system_one_client", return_value=client):
            outcome = rerank("gave up at checkout", candidates, team_id=1)

        assert outcome.reranked
        assert outcome.order == ["d", "b", "c", "a"]
        assert sorted(client.seen_texts) == ["a", "b", "c", "d"]

    def test_falls_back_to_embedding_order_when_no_gateway_is_configured(self) -> None:
        with patch(
            "products.replay_vision.backend.search_rerank.build_system_one_client",
            side_effect=SystemOneNotConfigured("no gateway"),
        ):
            outcome = rerank("gave up at checkout", _candidates("a", "b", "c"), team_id=1)

        assert not outcome.reranked
        assert outcome.order == ["a", "b", "c"]

    def test_falls_back_to_embedding_order_when_the_gateway_errors(self) -> None:
        client = MagicMock()
        client.decide.side_effect = SystemOneRequestFailed("HTTP 502", status_code=502)

        with patch("products.replay_vision.backend.search_rerank.build_system_one_client", return_value=client):
            outcome = rerank("gave up at checkout", _candidates("a", "b", "c"), team_id=1)

        assert not outcome.reranked
        assert outcome.order == ["a", "b", "c"]

    def test_falls_back_to_embedding_order_when_the_model_misses_the_deadline(self) -> None:
        candidates = _candidates("a", "b", "c")
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
