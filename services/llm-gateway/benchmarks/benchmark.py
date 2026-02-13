#!/usr/bin/env python3
"""Benchmark script measuring PostHog LLM gateway overhead vs direct provider calls.

Measures TTFT, TPS, and total latency for streaming and non-streaming requests
across multiple models, with sequential and concurrent modes.

Usage:
    python benchmark.py                          # all defaults
    python benchmark.py --iterations 10          # more iterations
    python benchmark.py --concurrency 5          # concurrent requests
    python benchmark.py --models gpt-4.1-mini claude-haiku-4-5-20251001
    python benchmark.py --streaming-only         # skip non-streaming
    python benchmark.py --report results/benchmark_20260213.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

DEFAULT_MODELS = [
    {"name": "gpt-4.1-mini", "provider": "openai"},
    {"name": "gpt-4.1-nano", "provider": "openai"},
    {"name": "claude-sonnet-4-5-20250514", "provider": "anthropic"},
    {"name": "claude-haiku-4-5-20251001", "provider": "anthropic"},
]

DEFAULT_PROMPT = "Write exactly 200 words about the history of computing."
DEFAULT_MAX_TOKENS = 300
DEFAULT_ITERATIONS = 5
DEFAULT_WARMUP = 1
DEFAULT_CONCURRENCY = 1
DEFAULT_OUTPUT_DIR = "results"


@dataclass
class BenchmarkResult:
    model: str
    route: str  # "direct" | "gateway"
    mode: str  # "streaming" | "non_streaming"
    ttft_ms: float | None  # only for streaming
    tps: float | None  # only for streaming
    total_ms: float
    token_count: int


@dataclass
class BenchmarkStats:
    mean: float
    median: float
    p95: float
    stddev: float


def compute_stats(values: list[float]) -> BenchmarkStats:
    if not values:
        return BenchmarkStats(mean=0, median=0, p95=0, stddev=0)
    mean = statistics.mean(values)
    median = statistics.median(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    sorted_vals = sorted(values)
    p95_idx = math.ceil(len(sorted_vals) * 0.95) - 1
    p95 = sorted_vals[max(0, p95_idx)]
    return BenchmarkStats(mean=mean, median=median, p95=p95, stddev=stddev)


def unique_prompt(prompt: str) -> str:
    return f"[{uuid.uuid4()}] {prompt}"


# -- Streaming benchmarks --


async def bench_openai_stream(
    client: AsyncOpenAI, model: str, prompt: str, max_tokens: int, route: str
) -> BenchmarkResult:
    start = time.perf_counter()
    ttft: float | None = None
    token_count = 0

    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": unique_prompt(prompt)}],
        max_tokens=max_tokens,
        temperature=0,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if ttft is None:
                ttft = (time.perf_counter() - start) * 1000
            token_count += 1

    total_ms = (time.perf_counter() - start) * 1000
    ttft_ms = ttft if ttft is not None else total_ms

    generation_ms = total_ms - ttft_ms
    tps = (token_count / (generation_ms / 1000)) if generation_ms > 0 and token_count > 0 else None

    return BenchmarkResult(
        model=model,
        route=route,
        mode="streaming",
        ttft_ms=ttft_ms,
        tps=tps,
        total_ms=total_ms,
        token_count=token_count,
    )


async def bench_anthropic_stream(
    client: AsyncAnthropic, model: str, prompt: str, max_tokens: int, route: str
) -> BenchmarkResult:
    start = time.perf_counter()
    ttft: float | None = None
    token_count = 0

    async with client.messages.stream(
        model=model,
        messages=[{"role": "user", "content": unique_prompt(prompt)}],
        max_tokens=max_tokens,
        temperature=0,
    ) as stream:
        async for text in stream.text_stream:
            if ttft is None:
                ttft = (time.perf_counter() - start) * 1000
            token_count += 1

    total_ms = (time.perf_counter() - start) * 1000
    ttft_ms = ttft if ttft is not None else total_ms

    generation_ms = total_ms - ttft_ms
    tps = (token_count / (generation_ms / 1000)) if generation_ms > 0 and token_count > 0 else None

    return BenchmarkResult(
        model=model,
        route=route,
        mode="streaming",
        ttft_ms=ttft_ms,
        tps=tps,
        total_ms=total_ms,
        token_count=token_count,
    )


# -- Non-streaming benchmarks --


async def bench_openai_non_stream(
    client: AsyncOpenAI, model: str, prompt: str, max_tokens: int, route: str
) -> BenchmarkResult:
    start = time.perf_counter()

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": unique_prompt(prompt)}],
        max_tokens=max_tokens,
        temperature=0,
        stream=False,
    )

    total_ms = (time.perf_counter() - start) * 1000
    token_count = response.usage.completion_tokens if response.usage else 0

    return BenchmarkResult(
        model=model,
        route=route,
        mode="non_streaming",
        ttft_ms=None,
        tps=None,
        total_ms=total_ms,
        token_count=token_count,
    )


async def bench_anthropic_non_stream(
    client: AsyncAnthropic, model: str, prompt: str, max_tokens: int, route: str
) -> BenchmarkResult:
    start = time.perf_counter()

    response = await client.messages.create(
        model=model,
        messages=[{"role": "user", "content": unique_prompt(prompt)}],
        max_tokens=max_tokens,
        temperature=0,
    )

    total_ms = (time.perf_counter() - start) * 1000
    token_count = response.usage.output_tokens

    return BenchmarkResult(
        model=model,
        route=route,
        mode="non_streaming",
        ttft_ms=None,
        tps=None,
        total_ms=total_ms,
        token_count=token_count,
    )


# -- Client setup --


def create_clients(
    gateway_url: str,
) -> dict[str, AsyncOpenAI | AsyncAnthropic]:
    gateway_api_key = os.environ.get("GATEWAY_API_KEY", "")

    clients: dict[str, AsyncOpenAI | AsyncAnthropic] = {}

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        clients["openai_direct"] = AsyncOpenAI(api_key=openai_key)
        # OpenAI SDK base_url replaces .../v1
        clients["openai_gateway"] = AsyncOpenAI(
            base_url=f"{gateway_url}/v1", api_key=gateway_api_key
        )

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        clients["anthropic_direct"] = AsyncAnthropic(api_key=anthropic_key)
        # Anthropic SDK adds /v1 itself
        clients["anthropic_gateway"] = AsyncAnthropic(
            base_url=gateway_url, api_key=gateway_api_key
        )

    return clients


def get_bench_fn(
    provider: str, mode: str, client: AsyncOpenAI | AsyncAnthropic
):
    fns = {
        ("openai", "streaming"): bench_openai_stream,
        ("openai", "non_streaming"): bench_openai_non_stream,
        ("anthropic", "streaming"): bench_anthropic_stream,
        ("anthropic", "non_streaming"): bench_anthropic_non_stream,
    }
    return fns[(provider, mode)]


# -- Runner --


async def run_single(
    bench_fn,
    client: AsyncOpenAI | AsyncAnthropic,
    model: str,
    prompt: str,
    max_tokens: int,
    route: str,
) -> BenchmarkResult:
    return await bench_fn(client, model, prompt, max_tokens, route)


async def run_benchmark(
    models: list[dict],
    iterations: int,
    warmup: int,
    concurrency: int,
    prompt: str,
    max_tokens: int,
    modes: list[str],
    gateway_url: str,
) -> list[BenchmarkResult]:
    clients = create_clients(gateway_url)
    all_results: list[BenchmarkResult] = []

    for model_cfg in models:
        model_name = model_cfg["name"]
        provider = model_cfg["provider"]

        direct_key = f"{provider}_direct"
        gateway_key = f"{provider}_gateway"

        if direct_key not in clients:
            print(f"  Skipping {model_name}: no {provider} API key configured")
            continue

        routes = [("direct", direct_key), ("gateway", gateway_key)]

        for mode in modes:
            # Warmup each route
            for route, client_key in routes:
                client = clients[client_key]
                bench_fn = get_bench_fn(provider, mode, client)
                label = f"{model_name} / {route} / {mode}"
                for i in range(warmup):
                    print(f"  {label} — warmup {i + 1}/{warmup}")
                    try:
                        await run_single(bench_fn, client, model_name, prompt, max_tokens, route)
                    except Exception as e:
                        print(f"    warmup error: {e}")

            # Interleaved measured iterations — direct/gateway back-to-back
            for i in range(iterations):
                for route, client_key in routes:
                    client = clients[client_key]
                    bench_fn = get_bench_fn(provider, mode, client)
                    label = f"{model_name} / {route} / {mode}"
                    print(f"  {label} — iteration {i + 1}/{iterations}")
                    try:
                        result = await run_single(
                            bench_fn, client, model_name, prompt, max_tokens, route
                        )
                        all_results.append(result)
                    except Exception as e:
                        print(f"    error: {e}")

            # Concurrent iterations — also interleaved per route
            if concurrency > 1:
                for route, client_key in routes:
                    client = clients[client_key]
                    bench_fn = get_bench_fn(provider, mode, client)
                    label = f"{model_name} / {route} / {mode}"
                    print(f"  {label} — concurrent ({concurrency})")
                    try:
                        concurrent_results = await asyncio.gather(
                            *[
                                run_single(bench_fn, client, model_name, prompt, max_tokens, route)
                                for _ in range(concurrency)
                            ],
                            return_exceptions=True,
                        )
                        for r in concurrent_results:
                            if isinstance(r, Exception):
                                print(f"    concurrent error: {r}")
                            else:
                                r.mode = f"concurrent_{mode}"
                                all_results.append(r)
                    except Exception as e:
                        print(f"    concurrent error: {e}")

    return all_results


# -- Stats aggregation --


def aggregate_stats(
    results: list[BenchmarkResult],
) -> dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]]:
    grouped: dict[str, dict[str, dict[str, list[BenchmarkResult]]]] = {}

    for r in results:
        grouped.setdefault(r.model, {}).setdefault(r.mode, {}).setdefault(r.route, []).append(r)

    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]] = {}
    for model, modes in grouped.items():
        stats[model] = {}
        for mode, routes in modes.items():
            stats[model][mode] = {}
            for route, route_results in routes.items():
                route_stats: dict[str, BenchmarkStats] = {
                    "total_ms": compute_stats([r.total_ms for r in route_results]),
                }
                ttft_values = [r.ttft_ms for r in route_results if r.ttft_ms is not None]
                if ttft_values:
                    route_stats["ttft_ms"] = compute_stats(ttft_values)
                tps_values = [r.tps for r in route_results if r.tps is not None]
                if tps_values:
                    route_stats["tps"] = compute_stats(tps_values)
                stats[model][mode][route] = route_stats

    return stats


# -- Output formatting --


def fmt_stat(s: BenchmarkStats) -> str:
    return f"{s.mean:.0f} / {s.median:.0f} / {s.p95:.0f}"


def fmt_overhead(direct: BenchmarkStats, gateway: BenchmarkStats, higher_is_better: bool = False) -> str:
    diff = gateway.mean - direct.mean
    pct = (diff / direct.mean * 100) if direct.mean != 0 else 0
    sign = "+" if diff >= 0 else ""
    if higher_is_better:
        quality = " (!)" if diff < 0 and abs(pct) > 20 else ""
    else:
        quality = " (!)" if diff > 0 and pct > 20 else ""
    return f"{sign}{diff:.0f} ({sign}{pct:.1f}%){quality}"


def print_streaming_table(
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]],
    mode: str,
    title: str,
) -> None:
    models_with_mode = [(m, s) for m, s in stats.items() if mode in s]
    if not models_with_mode:
        return

    print(f"\n{'=' * 3} {title} {'=' * 3}")
    header = f"{'Model':<30} {'Route':<10} {'TTFT (ms)':<22} {'TPS':<22} {'Total (ms)':<22}"
    subheader = f"{'':<30} {'':<10} {'mean / med / p95':<22} {'mean / med / p95':<22} {'mean / med / p95':<22}"
    print(header)
    print(subheader)
    print("─" * 106)

    for model, model_stats in models_with_mode:
        mode_stats = model_stats[mode]
        for route in ["direct", "gateway"]:
            if route not in mode_stats:
                continue
            rs = mode_stats[route]
            ttft_str = fmt_stat(rs["ttft_ms"]) if "ttft_ms" in rs else "—"
            tps_str = fmt_stat(rs["tps"]) if "tps" in rs else "—"
            total_str = fmt_stat(rs["total_ms"])
            print(f"{model:<30} {route:<10} {ttft_str:<22} {tps_str:<22} {total_str:<22}")

        if "direct" in mode_stats and "gateway" in mode_stats:
            d, g = mode_stats["direct"], mode_stats["gateway"]
            parts = ["  → overhead", ""]
            parts.append(
                fmt_overhead(d["ttft_ms"], g["ttft_ms"])
                if "ttft_ms" in d and "ttft_ms" in g
                else "—"
            )
            parts.append(
                fmt_overhead(d["tps"], g["tps"], higher_is_better=True)
                if "tps" in d and "tps" in g
                else "—"
            )
            parts.append(fmt_overhead(d["total_ms"], g["total_ms"]))
            print(f"{parts[0]:<30} {parts[1]:<10} {parts[2]:<22} {parts[3]:<22} {parts[4]:<22}")
        print()


def print_non_streaming_table(
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]],
    mode: str,
    title: str,
) -> None:
    models_with_mode = [(m, s) for m, s in stats.items() if mode in s]
    if not models_with_mode:
        return

    print(f"\n{'=' * 3} {title} {'=' * 3}")
    header = f"{'Model':<30} {'Route':<10} {'Total (ms)':<22}"
    subheader = f"{'':<30} {'':<10} {'mean / med / p95':<22}"
    print(header)
    print(subheader)
    print("─" * 62)

    for model, model_stats in models_with_mode:
        mode_stats = model_stats[mode]
        for route in ["direct", "gateway"]:
            if route not in mode_stats:
                continue
            total_str = fmt_stat(mode_stats[route]["total_ms"])
            print(f"{model:<30} {route:<10} {total_str:<22}")

        if "direct" in mode_stats and "gateway" in mode_stats:
            overhead = fmt_overhead(mode_stats["direct"]["total_ms"], mode_stats["gateway"]["total_ms"])
            print(f"{'  → overhead':<30} {'':<10} {overhead:<22}")
        print()


def print_results(
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]],
    concurrency: int,
) -> None:
    print_streaming_table(stats, "streaming", "Streaming Results")
    print_non_streaming_table(stats, "non_streaming", "Non-streaming Results")

    if concurrency > 1:
        print_streaming_table(stats, "concurrent_streaming", f"Concurrent ({concurrency}) Streaming Results")
        print_non_streaming_table(
            stats, "concurrent_non_streaming", f"Concurrent ({concurrency}) Non-streaming Results"
        )


# -- Persistence --


def stats_to_dict(
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]],
) -> dict:
    out: dict = {}
    for model, modes in stats.items():
        out[model] = {}
        for mode, routes in modes.items():
            out[model][mode] = {}
            for route, metrics in routes.items():
                out[model][mode][route] = {k: asdict(v) for k, v in metrics.items()}
    return out


def save_results(
    results: list[BenchmarkResult],
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]],
    metadata: dict,
    output_dir: str,
) -> str:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = path / f"benchmark_{timestamp}.json"

    data = {
        "metadata": metadata,
        "raw_results": [asdict(r) for r in results],
        "stats": stats_to_dict(stats),
    }

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nResults saved to {filename}")
    return str(filename)


def load_and_print_report(report_path: str) -> None:
    with open(report_path) as f:
        data = json.load(f)

    meta = data["metadata"]
    print(f"Report from {meta['timestamp']}")
    print(f"  iterations={meta['iterations']}, warmup={meta['warmup']}, concurrency={meta['concurrency']}")
    print(f"  max_tokens={meta['max_tokens']}")
    print(f"  prompt: {meta['prompt'][:80]}...")

    raw_stats = data["stats"]
    stats: dict[str, dict[str, dict[str, dict[str, BenchmarkStats]]]] = {}
    for model, modes in raw_stats.items():
        stats[model] = {}
        for mode, routes in modes.items():
            stats[model][mode] = {}
            for route, metrics in routes.items():
                stats[model][mode][route] = {
                    k: BenchmarkStats(**v) for k, v in metrics.items()
                }

    print_results(stats, meta["concurrency"])


# -- CLI --


def resolve_models(model_names: list[str] | None) -> list[dict]:
    if not model_names:
        return DEFAULT_MODELS

    model_lookup = {m["name"]: m for m in DEFAULT_MODELS}
    resolved = []
    for name in model_names:
        if name in model_lookup:
            resolved.append(model_lookup[name])
        elif name.startswith("claude"):
            resolved.append({"name": name, "provider": "anthropic"})
        else:
            resolved.append({"name": name, "provider": "openai"})
    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark LLM gateway overhead")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--models", nargs="+", default=None)
    parser.add_argument("--streaming-only", action="store_true")
    parser.add_argument("--non-streaming-only", action="store_true")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--report", default=None, help="Path to saved JSON to re-print")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("GATEWAY_URL", "https://gateway.us.posthog.com"),
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.report:
        load_and_print_report(args.report)
        return

    models = resolve_models(args.models)

    modes: list[str] = []
    if args.streaming_only:
        modes = ["streaming"]
    elif args.non_streaming_only:
        modes = ["non_streaming"]
    else:
        modes = ["streaming", "non_streaming"]

    print(f"Benchmarking {len(models)} models, {args.iterations} iterations, "
          f"{args.warmup} warmup, concurrency={args.concurrency}")
    print(f"Modes: {', '.join(modes)}")
    print(f"Prompt: {args.prompt[:80]}...")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Gateway: {args.gateway_url}")
    print()

    results = await run_benchmark(
        models=models,
        iterations=args.iterations,
        warmup=args.warmup,
        concurrency=args.concurrency,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        modes=modes,
        gateway_url=args.gateway_url,
    )

    if not results:
        print("No results collected. Check API keys and connectivity.")
        return

    stats = aggregate_stats(results)
    print_results(stats, args.concurrency)

    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iterations": args.iterations,
        "warmup": args.warmup,
        "concurrency": args.concurrency,
        "prompt": args.prompt,
        "max_tokens": args.max_tokens,
        "models": [m["name"] for m in models],
        "modes": modes,
    }

    save_results(results, stats, metadata, args.output_dir)


if __name__ == "__main__":
    asyncio.run(main())
