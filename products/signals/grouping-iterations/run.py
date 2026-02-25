"""
Main entry point for running grouping strategies.

Usage:
    python products/signals/grouping-iterations/run.py [--strategy current] [--limit N] [--skip-eval]
"""

import sys
import asyncio
import logging
import argparse
from pathlib import Path

# Add the grouping-iterations directory to the Python path so we can import
# harness, current_strategy, evaluate as top-level modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import evaluate_grouping, format_evaluation
from harness import EmbeddingCache, format_grouping_result, load_test_signals, run_harness

logger = logging.getLogger(__name__)


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

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Strategy: %s", args.strategy)

    # Load test signals
    signals = load_test_signals()
    if args.limit:
        signals = signals[: args.limit]
    logger.info("Loaded %d test signals", len(signals))

    # Initialize
    embedding_cache = EmbeddingCache()
    strategy = get_strategy(args.strategy)

    # Run the harness
    result = await run_harness(strategy, signals, embedding_cache)

    # Print results
    logger.info("\n%s", format_grouping_result(result))

    # Evaluate
    if not args.skip_eval:
        logger.info("Running LLM evaluation...")
        evaluation = await evaluate_grouping(result)
        logger.info("\n%s", format_evaluation(evaluation, result))
    else:
        logger.info("(evaluation skipped)")


if __name__ == "__main__":
    asyncio.run(main())
