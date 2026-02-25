"""
Main entry point for running grouping strategies.

Usage:
    python products/signals/grouping-iterations/run.py [--strategy current] [--limit N] [--skip-eval]
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add the grouping-iterations directory to the Python path so we can import
# harness, current_strategy, evaluate as top-level modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import EmbeddingCache, GroupingResult, load_test_signals, print_grouping_result, run_harness
from evaluate import evaluate_grouping, print_evaluation


def get_strategy(name: str):
    if name == "current":
        from current_strategy import CurrentStrategy

        return CurrentStrategy()
    else:
        raise ValueError(f"Unknown strategy: {name}. Available: current")


async def main():
    parser = argparse.ArgumentParser(description="Run signal grouping strategies")
    parser.add_argument("--strategy", default="current", help="Strategy to use (default: current)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of signals to process")
    parser.add_argument("--skip-eval", action="store_true", help="Skip LLM evaluation")
    args = parser.parse_args()

    print(f"Strategy: {args.strategy}")

    # Load test signals
    signals = load_test_signals()
    if args.limit:
        signals = signals[: args.limit]
    print(f"Loaded {len(signals)} test signals")

    # Initialize
    embedding_cache = EmbeddingCache()
    strategy = get_strategy(args.strategy)

    # Run the harness
    result = await run_harness(strategy, signals, embedding_cache)

    # Print results
    print_grouping_result(result)

    # Evaluate
    if not args.skip_eval:
        print("Running LLM evaluation...")
        evaluation = await evaluate_grouping(result)
        print_evaluation(evaluation, result)
    else:
        print("(evaluation skipped)")


if __name__ == "__main__":
    asyncio.run(main())
