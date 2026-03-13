# ruff: noqa: T201, E402
"""
Analyze the relationship between signal descriptions and their LLM-generated search queries.

Runs the query generation step (no matching) on each signal, captures the queries,
embeds everything, and compares:
1. Signal → its own queries (how far does the LLM stray from the source text?)
2. Signal → other signals' queries (do queries from one signal land near related signals?)
3. Query diversity per signal (do the 1-3 queries spread out or cluster?)

Usage:
    python products/signals/experiments/statistics/query_analysis.py [--limit N]
"""

import sys
import json
import asyncio
import logging
import argparse
from pathlib import Path

import numpy as np

# Add grouping-iterations to path for imports
HARNESS_DIR = Path(__file__).resolve().parent.parent / "grouping"
sys.path.insert(0, str(HARNESS_DIR))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent.parent.parent / ".env")

from current_strategy import MAX_QUERY_TOKENS, QueryGenerationResponse, _build_query_generation_system_prompt
from harness import EmbeddingCache, SignalTypeExample, call_llm_standalone, load_test_signals

logger = logging.getLogger(__name__)


async def generate_queries_for_signal(
    content: str,
    source_product: str,
    source_type: str,
    type_examples: list[SignalTypeExample] | None = None,
) -> list[str]:
    """Generate search queries for a signal using the production prompt."""
    system_prompt = _build_query_generation_system_prompt(type_examples or [])
    user_prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {content}"""

    def validate(text: str) -> list[str]:
        data = json.loads(text)
        result = QueryGenerationResponse.model_validate(data)
        return [q[: MAX_QUERY_TOKENS * 4] for q in result.queries]

    return await call_llm_standalone(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        validate=validate,
        temperature=0.7,
    )


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between two vectors."""
    a_norm = a / (np.linalg.norm(a) or 1)
    b_norm = b / (np.linalg.norm(b) or 1)
    return float(1 - np.dot(a_norm, b_norm))


async def main():
    parser = argparse.ArgumentParser(description="Query vs signal embedding analysis")
    parser.add_argument("--limit", type=int, default=None, help="Limit signals to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    signals = load_test_signals()
    if args.limit:
        signals = signals[: args.limit]

    embedding_cache = EmbeddingCache()

    print(f"Processing {len(signals)} signals...\n")

    all_results = []

    for i, sig in enumerate(signals):
        print(f"[{i + 1}/{len(signals)}] {sig.content[:80]}...")

        # Generate queries
        queries = await generate_queries_for_signal(
            sig.content,
            sig.source_product,
            sig.source_type,
        )
        print(f"  Queries ({len(queries)}):")
        for q in queries:
            print(f"    - {q[:120]}")

        # Embed signal and queries
        sig_emb = np.array(embedding_cache.embed(sig.content))
        query_embs = [np.array(embedding_cache.embed(q)) for q in queries]

        # Signal → query distances
        sig_to_query_dists = [cosine_distance(sig_emb, qe) for qe in query_embs]
        print(f"  Signal→query distances: {[f'{d:.4f}' for d in sig_to_query_dists]}")

        # Query-query distances (if 2+ queries)
        query_query_dists = []
        if len(query_embs) >= 2:
            for qi in range(len(query_embs)):
                for qj in range(qi + 1, len(query_embs)):
                    query_query_dists.append(cosine_distance(query_embs[qi], query_embs[qj]))
            print(f"  Query↔query distances: {[f'{d:.4f}' for d in query_query_dists]}")

        all_results.append(
            {
                "signal_id": sig.signal_id,
                "content_preview": sig.content[:200],
                "source_product": sig.source_product,
                "source_type": sig.source_type,
                "original_report_id": sig.original_report_id,
                "queries": queries,
                "signal_to_query_distances": sig_to_query_dists,
                "query_to_query_distances": query_query_dists,
            }
        )
        print()

    # Summary statistics
    all_sig_to_query = [d for r in all_results for d in r["signal_to_query_distances"]]
    all_query_to_query = [d for r in all_results for d in r["query_to_query_distances"]]

    print("=" * 80)
    print(f"\n=== SUMMARY ({len(signals)} signals, {len(all_sig_to_query)} signal→query pairs) ===\n")

    stq = np.array(all_sig_to_query)
    print(f"Signal → Query distance:")
    print(f"  mean={stq.mean():.4f}  std={stq.std():.4f}  min={stq.min():.4f}  max={stq.max():.4f}")
    print(f"  p25={np.percentile(stq, 25):.4f}  p50={np.percentile(stq, 50):.4f}  p75={np.percentile(stq, 75):.4f}")

    if all_query_to_query:
        qtq = np.array(all_query_to_query)
        print(f"\nQuery ↔ Query distance (within same signal):")
        print(f"  mean={qtq.mean():.4f}  std={qtq.std():.4f}  min={qtq.min():.4f}  max={qtq.max():.4f}")
        print(f"  p25={np.percentile(qtq, 25):.4f}  p50={np.percentile(qtq, 50):.4f}  p75={np.percentile(qtq, 75):.4f}")

    # Cross-signal analysis: do queries land closer to related signals?
    print(f"\n=== CROSS-SIGNAL QUERY TARGETING ===")
    print(f"  For each query, how close is it to its own signal vs other signals?\n")

    # Build signal embedding matrix
    sig_embs = np.array([embedding_cache.embed(sig.content) for sig in signals])
    sig_norms = np.linalg.norm(sig_embs, axis=1, keepdims=True)
    sig_norms = np.where(sig_norms == 0, 1, sig_norms)
    sig_normed = sig_embs / sig_norms

    own_ranks = []
    own_dists = []
    same_report_ranks = []

    for i, result in enumerate(all_results):
        for q_text in result["queries"]:
            q_emb = np.array(embedding_cache.embed(q_text))
            q_norm = q_emb / (np.linalg.norm(q_emb) or 1)

            # Distance to all signals
            dists = 1 - sig_normed @ q_norm
            ranked_indices = np.argsort(dists)

            # Where does the query's own signal rank?
            own_rank = int(np.where(ranked_indices == i)[0][0])
            own_ranks.append(own_rank)
            own_dists.append(float(dists[i]))

            # Where do same-report signals rank?
            own_report = result["original_report_id"]
            for j, sig in enumerate(signals):
                if j != i and sig.original_report_id == own_report:
                    rank = int(np.where(ranked_indices == j)[0][0])
                    same_report_ranks.append(rank)

    own_ranks_arr = np.array(own_ranks)
    print(f"Query's own signal rank (0 = closest, lower = better):")
    print(
        f"  mean={own_ranks_arr.mean():.1f}  median={np.median(own_ranks_arr):.0f}  "
        f"p90={np.percentile(own_ranks_arr, 90):.0f}  max={own_ranks_arr.max()}"
    )
    print(
        f"  rank 0 (best): {(own_ranks_arr == 0).sum()}/{len(own_ranks_arr)} ({100 * (own_ranks_arr == 0).mean():.0f}%)"
    )
    print(f"  rank <3: {(own_ranks_arr < 3).sum()}/{len(own_ranks_arr)} ({100 * (own_ranks_arr < 3).mean():.0f}%)")
    print(f"  rank <5: {(own_ranks_arr < 5).sum()}/{len(own_ranks_arr)} ({100 * (own_ranks_arr < 5).mean():.0f}%)")

    if same_report_ranks:
        sr = np.array(same_report_ranks)
        print(f"\nSame-report signal rank (other signals in the gold group):")
        print(f"  mean={sr.mean():.1f}  median={np.median(sr):.0f}  p90={np.percentile(sr, 90):.0f}  max={sr.max()}")
        print(f"  rank <5: {(sr < 5).sum()}/{len(sr)} ({100 * (sr < 5).mean():.0f}%)")
        print(f"  rank <10: {(sr < 10).sum()}/{len(sr)} ({100 * (sr < 10).mean():.0f}%)")

    # Save results
    output_path = Path("/tmp/embedding_analysis/query_analysis.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nDetailed results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
