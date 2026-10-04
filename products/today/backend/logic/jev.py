import json
import time
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
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, GatewaySystemOneClient, build_system_one_client

from ..facade import contracts

_AI_PRODUCT = "today_report"
_CONCURRENCY = 4
_DEADLINE_SECONDS = 45
_REQUEST_SECONDS = 30
_CACHE_SECONDS = 30 * 24 * 60 * 60


@frozen
class JevPick:
    label: str
    probability: float


class JevClient(Protocol):
    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]: ...

    def yes_probability(self, items: list[str], question: str) -> list[float | None]: ...


def _pick(answer: Answer) -> JevPick | None:
    return JevPick(label=answer.choice, probability=answer.confidence) if isinstance(answer, ChoiceAnswer) else None


def _probability(answer: Answer) -> float | None:
    return answer.probability if isinstance(answer, NoulAnswer) else None


def _outcome(task: asyncio.Task[list[Answer]]) -> list[Answer] | BaseException:
    if task.cancelled():
        return contracts.JevTimedOut()
    return task.exception() or task.result()


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
        )
        assert isinstance(client, GatewaySystemOneClient)
        return client

    def _cache_key(self, question: Question, item: str) -> str:
        body = json.dumps([self._team_id, self._model, question.to_json(), item], sort_keys=True)
        return f"today_jev:{hashlib.sha256(body.encode()).hexdigest()}"

    async def _ask_batch(self, items: list[str], question: Question, deadline: float) -> list[Answer]:
        keys = [f"row_{index}" for index in range(len(items))]
        questions: dict[str, Question] = {
            key: replace(
                question,
                instructions={"input": f"Evaluate only the text in state.{key}.", "question": question.instructions},
            )
            for key in keys
        }
        client = replace(self._client, timeout=min(deadline - time.monotonic(), _REQUEST_SECONDS))
        result = await client.adecide(state=dict(zip(keys, items)), questions=questions)
        return [result.answers[key] for key in keys]

    async def _ask(self, batches: list[list[str]], question: Question) -> list[list[Answer] | BaseException]:
        semaphore = asyncio.Semaphore(_CONCURRENCY)
        deadline = time.monotonic() + _DEADLINE_SECONDS

        async def ask_batch(batch: list[str]) -> list[Answer]:
            async with semaphore:
                return await self._ask_batch(batch, question, deadline)

        tasks = [asyncio.create_task(ask_batch(batch)) for batch in batches]
        try:
            await asyncio.wait(tasks, timeout=_DEADLINE_SECONDS)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return [_outcome(task) for task in tasks]

    def _answers[T](self, items: list[str], question: Question, value: Callable[[Answer], T]) -> list[T]:
        keys = [self._cache_key(question, item) for item in items]
        saved = cache.get_many(keys)
        missing = list({key: item for key, item in zip(keys, items) if key not in saved}.items())
        batches = [
            missing[start : start + GATEWAY_MAX_QUESTIONS] for start in range(0, len(missing), GATEWAY_MAX_QUESTIONS)
        ]
        outcomes = (
            async_to_sync(self._ask)([[item for _, item in batch] for batch in batches], question) if batches else []
        )
        fresh: dict[str, T] = {}
        failures: list[BaseException] = []
        for batch, outcome in zip(batches, outcomes):
            if isinstance(outcome, BaseException):
                failures.append(outcome)
            else:
                fresh |= {key: value(answer) for (key, _), answer in zip(batch, outcome)}
        cache.set_many(fresh, timeout=_CACHE_SECONDS)
        if failures:
            raise failures[0]
        found = saved | fresh
        return [found[key] for key in keys]

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        criteria: dict[str, None] = dict.fromkeys(labels)
        return self._answers(items, ChoiceQuestion(instructions=question, criteria=criteria), _pick)

    def yes_probability(self, items: list[str], question: str) -> list[float | None]:
        return self._answers(items, NoulQuestion(instructions=question), _probability)
