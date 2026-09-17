"""Collect a Replay Vision golden dataset from an existing project's observations.

Usage, from the repo root, with a personal API key that can read the source project:

    POSTHOG_API_KEY=... python -m products.replay_vision.evals.collect \\
        --project-id 2 --per-type 25 --output ~/.posthog/replay-vision-golden-dataset

Then point REPLAY_VISION_EVAL_DATASET at the output directory to run the eval suite.
The dataset contains real session data: keep it out of the repo and off any public surface.
"""

import os
import argparse
from pathlib import Path

import django

_DEFAULT_OUTPUT = "~/.posthog/replay-vision-golden-dataset"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="https://us.posthog.com", help="PostHog instance to collect from.")
    parser.add_argument("--project-id", type=int, default=2, help="Source project (default: PostHog dogfood).")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT, help="Dataset directory to write.")
    parser.add_argument("--per-type", type=int, default=25, help="Cases to collect per scanner type.")
    parser.add_argument(
        "--scanner-id", action="append", dest="scanner_ids", help="Restrict to specific scanner ids (repeatable)."
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed for the uniform sample, for reproducibility.")
    parser.add_argument(
        "--max-observations",
        type=int,
        default=200,
        help="Newest observations to consider per scanner; lower paginates much faster.",
    )
    parser.add_argument(
        "--upload",
        metavar="OBJECT_KEY",
        help="After collecting, upload the dataset into object storage under this key, "
        "replacing whatever the key held.",
    )
    parser.add_argument(
        "--from",
        dest="from_key",
        metavar="OBJECT_KEY",
        help="Download the pinned dataset under this key into --output first, then extend it with new cases.",
    )
    args = parser.parse_args()

    # Env var only, deliberately: a key passed as a CLI flag leaks into shell history and ps output.
    api_key = os.environ.get("POSTHOG_API_KEY", "")
    if not api_key:
        parser.error("set POSTHOG_API_KEY")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()
    from products.replay_vision.evals.collector import collect  # noqa: PLC0415 - needs Django configured first
    from products.replay_vision.evals.dataset import (  # noqa: PLC0415 - needs Django configured first
        download_pinned_dataset,
        upload_pinned_dataset,
    )

    output = Path(args.output).expanduser()
    if args.from_key:
        pinned = download_pinned_dataset(output, key=args.from_key)
        print(f"Loaded {len(pinned.cases)} pinned cases from {args.from_key}")  # noqa: T201

    dataset = collect(
        host=args.host,
        project_id=args.project_id,
        api_key=api_key,
        output=output,
        per_type=args.per_type,
        scanner_ids=args.scanner_ids,
        seed=args.seed,
        max_observations_per_scanner=args.max_observations,
    )
    if args.upload:
        upload_pinned_dataset(output, dataset, key=args.upload)
        print(f"Pinned {len(dataset.cases)} cases to {args.upload}")  # noqa: T201
    by_type: dict[str, int] = {}
    for case in dataset.cases:
        by_type[case.scanner_type] = by_type.get(case.scanner_type, 0) + 1
    labeled = sum(1 for case in dataset.cases if case.label_is_correct is not None)
    print(f"Collected {len(dataset.cases)} cases ({labeled} labeled): {by_type}")  # noqa: T201
    print(  # noqa: T201
        f"Run the suite with: REPLAY_VISION_EVAL_DATASET={args.output} GEMINI_API_KEY=... "
        "LLM_GATEWAY_ANTHROPIC_API_KEY=... BRAINTRUST_API_KEY=... hogli evals eval_scanner_quality"
    )


if __name__ == "__main__":
    main()
