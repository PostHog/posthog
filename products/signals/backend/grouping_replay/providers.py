"""Provider boundaries for enrichment and the optional semantic oracle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class SignatureProvider(Protocol):
    async def generate_signature(
        self,
        *,
        model: str,
        system_prompt: str,
        signal_payload: str,
    ) -> str: ...


class EmbeddingProvider(Protocol):
    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...


class OracleProvider(Protocol):
    async def complete(self, *, model: str, prompt: str, max_tokens: int) -> str: ...


@dataclass(frozen=True)
class ProviderSet:
    """Injected provider implementations.

    A caller can supply deterministic fakes, direct SDK adapters, or the PostHog
    gateway adapters. Only providers needed by a particular replay are required.
    """

    signatures: SignatureProvider | None = None
    embeddings: EmbeddingProvider | None = None
    oracle: OracleProvider | None = None
    aclose: Callable[[], Awaitable[None]] | None = None
