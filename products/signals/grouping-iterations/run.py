"""
Main entry point for running grouping strategies.

Usage:
    python products/signals/grouping-iterations/run.py [--strategy current] [--limit N] [--skip-eval] [--note "..."]
"""

import sys
import json
import asyncio
import logging
import argparse
from datetime import UTC, datetime
from pathlib import Path

# Add the grouping-iterations directory to the Python path so we can import
# harness, current_strategy, evaluate as top-level modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import compute_summary_metrics, evaluate_grouping, format_evaluation, format_metrics
from harness import EmbeddingCache, GroupingResult, format_grouping_result, load_test_signals, run_harness

logger = logging.getLogger(__name__)

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def get_strategy(name: str):
    if name == "pr_specificity_and_group_aware":
        from pr_specificity_and_group_aware import PRSpecificityAndGroupAwareStrategy

        return PRSpecificityAndGroupAwareStrategy()
    else:
        raise ValueError(f"Unknown strategy: {name}. Available: pr_specificity_and_group_aware")


def save_run(
    strategy_name: str,
    result: GroupingResult,
    evaluation: dict | None,
    metrics: dict | None,
    note: str | None,
    limit: int | None,
) -> Path:
    """Save run results to runs/ directory as a markdown file."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{strategy_name}.md"
    path = RUNS_DIR / filename

    lines: list[str] = []

    # Header with metadata
    lines.append(f"# Run: {strategy_name} — {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("## Context")
    lines.append("")
    lines.append(f"- **Strategy:** {strategy_name}")
    lines.append(f"- **Signals:** {len(result.signals)}{f' (limited from full set)' if limit else ''}")
    lines.append(f"- **Groups produced:** {len(result.groups)}")
    if note:
        lines.append(f"- **Note:** {note}")
    lines.append("")

    if metrics:
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        lines.append(f"| Overall score | {metrics['overall_score']}/5 |")
        lines.append(f"| Weighted coherence | {metrics['weighted_coherence']}/5.0 |")
        lines.append(
            f"| Groups | {metrics['group_count']} ({metrics['multi_signal_groups']} multi, {metrics['singletons']} single) |"
        )
        lines.append(f"| Weak-chain groups | {metrics['weak_chain_groups']} |")
        lines.append(f"| Misplaced signals | {metrics['total_misplaced']} |")
        lines.append(f"| Under-grouping misses | {metrics['undergrouping_misses']} |")
        lines.append("")

    # Per-signal processing log
    lines.append("## Processing log")
    lines.append("")
    for i, (signal, decision) in enumerate(result.decisions):
        content_preview = signal.content[:80].replace("\n", " ")
        action = "NEW GROUP" if decision.is_new else f"MATCHED -> {decision.report_id[:12]}..."
        lines.append(f"{i + 1}. `{content_preview}...`")
        lines.append(f"   - {action} | {decision.reason}")
    lines.append("")

    # Grouping results
    lines.append("## Groups")
    lines.append("")
    lines.append(format_grouping_result(result))
    lines.append("")

    # Evaluation
    if evaluation:
        lines.append("## Evaluation")
        lines.append("")
        lines.append(format_evaluation(evaluation))
        lines.append("")

    # Raw evaluation JSON for programmatic comparison
    if evaluation:
        lines.append("## Raw evaluation")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(evaluation, indent=2))
        lines.append("```")

    path.write_text("\n".join(lines))
    return path


async def main():
    parser = argparse.ArgumentParser(description="Run signal grouping strategies")
    parser.add_argument(
        "--strategy",
        default="pr_specificity_and_group_aware",
        help="Strategy to use (default: pr_specificity_and_group_aware)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of signals to process")
    parser.add_argument("--skip-eval", action="store_true", help="Skip LLM evaluation")
    parser.add_argument(
        "--note", default=None, help="Note to attach to this run (e.g. 'baseline' or 'added distance threshold')"
    )
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
    evaluation = None
    metrics = None
    if not args.skip_eval:
        logger.info("Running LLM evaluation...")
        evaluation = await evaluate_grouping(result)
        metrics = compute_summary_metrics(evaluation, result)
        logger.info("\n%s", format_metrics(metrics))
        logger.info("\n%s", format_evaluation(evaluation))
    else:
        logger.info("(evaluation skipped)")

    # Save run
    run_path = save_run(args.strategy, result, evaluation, metrics, args.note, args.limit)
    logger.info("\nRun saved to: %s", run_path)


if __name__ == "__main__":
    asyncio.run(main())
