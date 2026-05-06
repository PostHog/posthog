from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, Field

from products.signals.backend.temporal.llm import call_llm


class CanonicalSignal(BaseModel):
    """Source-agnostic signal shape produced by the LLM.

    Wrappers turn these into source-specific raw fixtures that the existing
    parsers (github_issue_emitter, linear_issue_emitter, etc.) accept unchanged.
    """

    title: str = Field(min_length=10, max_length=300)
    body: str = Field(min_length=20, max_length=4000)


class CanonicalSignalBatch(BaseModel):
    signals: list[CanonicalSignal] = Field(min_length=1, max_length=20)


T = TypeVar("T", bound=BaseModel)


def _validator(schema_cls: type[T]) -> Callable[[str], T]:
    def validate(text: str) -> T:
        return schema_cls.model_validate_json(text)

    return validate


async def generate_canonical_signals(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
) -> list[CanonicalSignal]:
    """Generate a batch of canonical signals via the signals LLM helper.

    Reuses `call_llm` from products.signals.backend.temporal.llm so we get the
    same retry-on-validation-failure behavior the rest of the pipeline uses.
    Model is controlled by the SIGNAL_MATCHING_LLM_MODEL env var (default
    claude-sonnet-4-5).
    """
    batch = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        validate=_validator(CanonicalSignalBatch),
        temperature=temperature,
    )
    return batch.signals
