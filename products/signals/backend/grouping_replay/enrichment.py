"""Parallel, cached concern-signature and embedding enrichment."""

from __future__ import annotations

import os
import json
import time
import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from products.signals.backend.grouping_replay.cache import append_jsonl, read_jsonl_cache
from products.signals.backend.grouping_replay.engine import (
    EMBEDDING_MODEL,
    SIGNATURE_MODEL,
    SIGNATURE_PROMPT_VERSION,
    SIGNATURE_SYSTEM_PROMPT,
    embedding_list,
    normalize_signature,
    signature_text,
)
from products.signals.backend.grouping_replay.providers import EmbeddingProvider, ProviderSet, SignatureProvider


def content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _signature_provider_input(row: dict[str, object]) -> tuple[str, str]:
    signal_payload = json.dumps(
        {
            "source_product": row["source_product"],
            "source_type": row["source_type"],
            "signal": row["content"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical_request = json.dumps(
        {
            "model": SIGNATURE_MODEL,
            "system_prompt": SIGNATURE_SYSTEM_PROMPT,
            "signal_payload": signal_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return signal_payload, content_sha256(canonical_request)


def parse_signature_response(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("signature response must be a JSON object")
    expected = {
        "polarity",
        "surface",
        "failure_mode",
        "error_anchor",
        "affected_entity",
        "concern_tags",
        "one_liner",
    }
    if set(value) != expected:
        raise ValueError(f"signature response fields differ: {sorted(set(value) ^ expected)}")
    if value["polarity"] not in {"problem", "success", "neutral"}:
        raise ValueError("invalid signature polarity")
    if not isinstance(value["concern_tags"], list):
        raise ValueError("concern_tags must be an array")
    return value


async def _with_retries(operation: Callable[[], Awaitable[object]]) -> object:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return await operation()
        except Exception as error:
            last_error = error
            if attempt < 2:
                await asyncio.sleep(2**attempt)
    assert last_error is not None
    raise last_error


async def generate_signatures(
    rows: list[dict[str, object]],
    cache_dir: Path,
    concurrency: int,
    provider: SignatureProvider | None,
) -> dict[str, int]:
    cache_path = cache_dir / "concern-signatures.jsonl"
    cache = read_jsonl_cache(cache_path, ("provider_input_sha256", "model", "prompt_version"))
    missing_by_hash: dict[str, tuple[str, list[dict[str, object]]]] = {}
    supplied = 0
    for row in rows:
        if row["concern_signature"] is not None:
            supplied += 1
            continue
        signal_payload, provider_input_hash = _signature_provider_input(row)
        if provider_input_hash not in missing_by_hash:
            missing_by_hash[provider_input_hash] = (signal_payload, [])
        missing_by_hash[provider_input_hash][1].append(row)

    cache_hits = 0
    pending: list[tuple[str, str, list[dict[str, object]]]] = []
    for provider_input_hash, (signal_payload, duplicates) in missing_by_hash.items():
        cached = cache.get((provider_input_hash, SIGNATURE_MODEL, SIGNATURE_PROMPT_VERSION))
        if cached is None:
            pending.append((provider_input_hash, signal_payload, duplicates))
            continue
        raw_signature = cached["signature"]
        normalized = normalize_signature(raw_signature)
        for row in duplicates:
            row["concern_signature"] = dict(normalized or {})
            row["signature_embedding_text"] = signature_text(raw_signature)
        cache_hits += 1

    if not pending:
        return {"supplied": supplied, "cache_hits": cache_hits, "calls": 0, "generated_signals": 0}
    if provider is None:
        raise ValueError("missing concern signatures require a signature provider or team_id")

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def generate_one(
        provider_input_hash: str, signal_payload: str, duplicates: list[dict[str, object]]
    ) -> tuple[str, list[dict[str, object]], dict[str, object]]:
        async def call() -> str:
            async with semaphore:
                return await provider.generate_signature(
                    model=SIGNATURE_MODEL,
                    system_prompt=SIGNATURE_SYSTEM_PROMPT,
                    signal_payload=signal_payload,
                )

        response = await _with_retries(call)
        return provider_input_hash, duplicates, parse_signature_response(str(response))

    tasks = [
        asyncio.create_task(generate_one(provider_input_hash, signal_payload, duplicates))
        for provider_input_hash, signal_payload, duplicates in pending
    ]
    try:
        for task in asyncio.as_completed(tasks):
            provider_input_hash, duplicates, raw_signature = await task
            append_jsonl(
                cache_path,
                {
                    "provider_input_sha256": provider_input_hash,
                    "model": SIGNATURE_MODEL,
                    "prompt_version": SIGNATURE_PROMPT_VERSION,
                    "signature": raw_signature,
                },
            )
            normalized = normalize_signature(raw_signature)
            for row in duplicates:
                row["concern_signature"] = dict(normalized or {})
                row["signature_embedding_text"] = signature_text(raw_signature)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "supplied": supplied,
        "cache_hits": cache_hits,
        "calls": len(tasks),
        "generated_signals": sum(len(duplicates) for _, _, duplicates in pending),
    }


async def embed_missing_values(
    values: dict[str, str],
    cache_path: Path,
    concurrency: int,
    provider: EmbeddingProvider | None,
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[dict[str, list[float]], dict[str, int]]:
    cache = read_jsonl_cache(cache_path, ("text_sha256", "model"))
    by_hash: dict[str, tuple[str, list[str]]] = {}
    for value_id, text in values.items():
        text_hash = content_sha256(text)
        if text_hash not in by_hash:
            by_hash[text_hash] = (text, [])
        by_hash[text_hash][1].append(value_id)

    result: dict[str, list[float]] = {}
    pending: list[tuple[str, str, list[str]]] = []
    cache_hits = 0
    for text_hash, (text, value_ids) in by_hash.items():
        cached = cache.get((text_hash, EMBEDDING_MODEL))
        if cached is None:
            pending.append((text_hash, text, value_ids))
            continue
        embedding = embedding_list(cached["embedding"], "cached embedding")
        for value_id in value_ids:
            result[value_id] = embedding
        cache_hits += len(value_ids)

    if not pending:
        return result, {"cache_hits": cache_hits, "calls": 0, "embedded_values": 0}
    if provider is None:
        raise ValueError("missing embeddings require an embedding provider or team_id")

    request_semaphore = semaphore or asyncio.Semaphore(max(concurrency, 1))

    async def embed_one(text_hash: str, text: str, value_ids: list[str]) -> tuple[str, list[str], list[float]]:
        async def call() -> list[list[float]]:
            async with request_semaphore:
                return await provider.embed(model=EMBEDDING_MODEL, texts=[text])

        raw_embeddings = await _with_retries(call)
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != 1:
            raise ValueError("embedding provider must return one vector for each request")
        return text_hash, value_ids, embedding_list(raw_embeddings[0], "provider embedding")

    tasks = [asyncio.create_task(embed_one(text_hash, text, value_ids)) for text_hash, text, value_ids in pending]
    try:
        for task in asyncio.as_completed(tasks):
            text_hash, value_ids, embedding = await task
            append_jsonl(
                cache_path,
                {"text_sha256": text_hash, "model": EMBEDDING_MODEL, "embedding": embedding},
            )
            for value_id in value_ids:
                result[value_id] = embedding
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return result, {
        "cache_hits": cache_hits,
        "calls": len(tasks),
        "embedded_values": sum(len(value_ids) for _, _, value_ids in pending),
        "unique_embedded_texts": len(pending),
    }


async def enrich_rows(
    rows: list[dict[str, object]],
    cache_dir: Path,
    providers: ProviderSet,
    signature_concurrency: int,
    embedding_concurrency: int,
) -> dict[str, object]:
    started = time.monotonic()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cache_dir, 0o700)
    signature_stats = await generate_signatures(rows, cache_dir, signature_concurrency, providers.signatures)
    missing_signals: dict[str, str] = {}
    missing_signatures: dict[str, str] = {}
    for row in rows:
        document_id = str(row["document_id"])
        if row["embedding"] is None:
            missing_signals[document_id] = str(row["content"])
        signature = row["concern_signature"]
        if isinstance(signature, dict) and not signature.get("emb"):
            missing_signatures[document_id] = str(row["signature_embedding_text"])
    embedding_semaphore = asyncio.Semaphore(embedding_concurrency)
    (
        (signal_embeddings, signal_embedding_stats),
        (signature_embeddings, signature_embedding_stats),
    ) = await asyncio.gather(
        embed_missing_values(
            missing_signals,
            cache_dir / "signal-embeddings.jsonl",
            embedding_concurrency,
            providers.embeddings,
            embedding_semaphore,
        ),
        embed_missing_values(
            missing_signatures,
            cache_dir / "concern-signature-embeddings.jsonl",
            embedding_concurrency,
            providers.embeddings,
            embedding_semaphore,
        ),
    )
    for row in rows:
        document_id = str(row["document_id"])
        if row["embedding"] is None:
            row["embedding"] = signal_embeddings[document_id]
        signature = row["concern_signature"]
        if isinstance(signature, dict) and not signature.get("emb"):
            signature_record = cast(dict[str, object], signature)
            signature_record["emb"] = signature_embeddings[document_id]
    return {
        "signature_model": SIGNATURE_MODEL,
        "signature_prompt_version": SIGNATURE_PROMPT_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "signature": signature_stats,
        "signal_embedding": signal_embedding_stats,
        "signature_embedding": signature_embedding_stats,
        "elapsed_seconds": time.monotonic() - started,
    }
