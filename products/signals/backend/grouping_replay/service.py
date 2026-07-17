"""Management-command-friendly service API for frozen Signals grouping replay."""

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from products.signals.backend.grouping_replay.artifacts import load_frozen_pipeline
from products.signals.backend.grouping_replay.bundle import build_bundle, inspect_bundle, write_bundle
from products.signals.backend.grouping_replay.engine import (
    EMBEDDING_CONCURRENCY,
    SIGNATURE_CONCURRENCY,
    PythonPipeline,
    materialize_signals,
)
from products.signals.backend.grouping_replay.enrichment import enrich_rows
from products.signals.backend.grouping_replay.input import load_input
from products.signals.backend.grouping_replay.oracle import OracleService
from products.signals.backend.grouping_replay.providers import ProviderSet

ReplayMode = Literal["oracle-off", "oracle-on"]
MAX_SIGNATURE_CONCURRENCY = 128
MAX_EMBEDDING_CONCURRENCY = 8


@dataclass(frozen=True)
class ReplayOptions:
    mode: ReplayMode = "oracle-off"
    team_id: int | None = None
    run_dir: Path | None = None
    signature_concurrency: int = SIGNATURE_CONCURRENCY
    embedding_concurrency: int = EMBEDDING_CONCURRENCY
    providers: ProviderSet | None = None


@dataclass(frozen=True)
class ReplayResult:
    output_path: Path
    run_dir: Path
    mode: ReplayMode
    signal_count: int
    report_count: int
    pipeline_fingerprint: str
    bundle: dict[str, object]


async def replay_signals(
    input_path: Path,
    output_path: Path,
    *,
    options: ReplayOptions | None = None,
) -> ReplayResult:
    """Enrich, chronologically replay, seal, and revalidate one portable bundle.

    When ``team_id`` is supplied and providers are not injected, all model calls
    use PostHog's Signals LLM gateway route with team attribution. Without a team,
    missing enrichment or oracle responses must be satisfied by injected providers
    or existing append-only run-directory cache entries.
    """

    selected = options or ReplayOptions()
    if selected.mode not in {"oracle-off", "oracle-on"}:
        raise ValueError("mode must be oracle-off or oracle-on")
    if selected.signature_concurrency < 1 or selected.embedding_concurrency < 1:
        raise ValueError("provider concurrency must be positive")
    if selected.signature_concurrency > MAX_SIGNATURE_CONCURRENCY:
        raise ValueError(f"signature concurrency cannot exceed {MAX_SIGNATURE_CONCURRENCY}")
    if selected.embedding_concurrency > MAX_EMBEDDING_CONCURRENCY:
        raise ValueError(f"embedding concurrency cannot exceed {MAX_EMBEDDING_CONCURRENCY}")
    output = output_path.resolve()
    run_dir = selected.run_dir.resolve() if selected.run_dir is not None else output.with_name(f"{output.name}.run")
    run_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(run_dir, 0o700)

    providers = selected.providers
    owns_providers = False
    if providers is None and selected.team_id is not None:
        from products.signals.backend.grouping_replay.provider_gateway import (  # noqa: PLC0415 -- optional Django edge
            gateway_provider_set,
        )

        providers = gateway_provider_set(selected.team_id)
        owns_providers = True
    providers = providers or ProviderSet()

    try:
        pipeline = load_frozen_pipeline()
        loaded = load_input(input_path)
        enrichment = await enrich_rows(
            loaded.rows,
            run_dir / "cache",
            providers,
            selected.signature_concurrency,
            selected.embedding_concurrency,
        )
        signals = materialize_signals(loaded.rows)
        oracle_service: OracleService | None = None
        if selected.mode == "oracle-on":
            modes = cast(dict[str, dict[str, object]], pipeline.configuration["modes"])
            engine_config = cast(dict[str, object], pipeline.configuration["engine_config"])
            oracle_service = OracleService(
                providers.oracle,
                run_dir / "cache" / "oracle",
                model=str(modes["oracle-on"]["oracle_model"]),
                max_tokens=int(engine_config["member_repair_llm_max_tokens"]),
            )
        replay = await PythonPipeline(
            signals,
            artifact_dir=pipeline.artifact_dir,
            oracle_service=oracle_service,
        ).run()
        bundle = build_bundle(
            signals=signals,
            replay=replay,
            mode=selected.mode,
            source_name=loaded.source_name,
            source_sha256=loaded.sha256,
            pipeline=pipeline,
            enrichment=enrichment,
            signature_concurrency=selected.signature_concurrency,
            embedding_concurrency=selected.embedding_concurrency,
            oracle_calls=oracle_service.calls if oracle_service is not None else 0,
            oracle_cache_hits=oracle_service.cache_hits if oracle_service is not None else 0,
        )
        write_bundle(output, bundle)
        inspection = inspect_bundle(output)
        return ReplayResult(
            output_path=output,
            run_dir=run_dir,
            mode=selected.mode,
            signal_count=inspection.signal_count,
            report_count=inspection.report_count,
            pipeline_fingerprint=inspection.pipeline_fingerprint,
            bundle=inspection.bundle,
        )
    finally:
        if owns_providers and providers.aclose is not None:
            await providers.aclose()


def replay_signals_sync(
    input_path: Path,
    output_path: Path,
    *,
    options: ReplayOptions | None = None,
) -> ReplayResult:
    """Synchronous wrapper intended for Django management commands."""

    return asyncio.run(replay_signals(input_path, output_path, options=options))
