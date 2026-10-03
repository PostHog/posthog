import json
import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import replace
from functools import cached_property
from typing import Protocol

from django.conf import settings
from django.core.cache import cache

from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.llm.system_one import Answer, ChoiceAnswer, ChoiceQuestion, NoulAnswer, NoulQuestion, Question
from posthog.llm.system_one_client import GatewaySystemOneClient, build_system_one_client

_AI_PRODUCT = "today_report"
_STATE_KEY = "row_0"
_CONCURRENCY = 4
_CACHE_SECONDS = 30 * 24 * 60 * 60


@frozen
class JevPick:
    label: str
    probability: float


class JevClient(Protocol):
    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]: ...

    def yes(self, items: list[str], question: str) -> list[float | None]: ...


def _pick(answer: Answer) -> JevPick | None:
    return JevPick(label=answer.choice, probability=answer.confidence) if isinstance(answer, ChoiceAnswer) else None


def _probability(answer: Answer) -> float | None:
    return answer.probability if isinstance(answer, NoulAnswer) else None


class GatewayJev:
    def __init__(self, *, team_id: int, distinct_id: str, model: str | None = None) -> None:
        self._team_id = team_id
        self._distinct_id = distinct_id
        self._model = model or settings.HOGQL_PROMPT_JEV_MODEL

    @cached_property
    def _client(self) -> GatewaySystemOneClient:
        client = build_system_one_client(
            model=self._model,
            ai_product=_AI_PRODUCT,
            team_id=self._team_id,
            distinct_id=self._distinct_id,
            properties={"team_id": str(self._team_id)},
        )
        assert isinstance(client, GatewaySystemOneClient)
        return client

    def _cache_key(self, question: Question, item: str) -> str:
        body = json.dumps([self._team_id, self._model, question.to_json(), item], sort_keys=True)
        return f"today_jev:{hashlib.sha256(body.encode()).hexdigest()}"

    async def _ask(self, items: list[str], question: Question) -> list[Answer]:
        semaphore = asyncio.Semaphore(_CONCURRENCY)
        wrapped = replace(
            question,
            instructions={"input": f"Evaluate only the text in state.{_STATE_KEY}.", "question": question.instructions},
        )

        async def ask_one(item: str) -> Answer:
            async with semaphore:
                result = await self._client.adecide(state={_STATE_KEY: item}, questions={_STATE_KEY: wrapped})
            return result.answers[_STATE_KEY]

        return list(await asyncio.gather(*(ask_one(item) for item in items)))

    def _answers[T](self, items: list[str], question: Question, value: Callable[[Answer], T]) -> list[T]:
        keys = [self._cache_key(question, item) for item in items]
        saved = cache.get_many(keys)
        missing = {key: item for key, item in zip(keys, items) if key not in saved}
        answers = async_to_sync(self._ask)(list(missing.values()), question) if missing else []
        fresh = {key: value(answer) for key, answer in zip(missing, answers)}
        cache.set_many(fresh, timeout=_CACHE_SECONDS)
        found = saved | fresh
        return [found[key] for key in keys]

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        criteria: dict[str, None] = dict.fromkeys(labels)
        return self._answers(items, ChoiceQuestion(instructions=question, criteria=criteria), _pick)

    def yes(self, items: list[str], question: str) -> list[float | None]:
        return self._answers(items, NoulQuestion(instructions=question), _probability)
