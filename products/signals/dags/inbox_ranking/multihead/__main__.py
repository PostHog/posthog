"""Run the multi-head prototype against the snapshots `bin/sync_snapshots_local.sh` cached on disk.

    uv sync --group inbox-ranking
    INBOX_RANKING_SYNC_EMBEDDINGS=1 products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
    DEBUG=1 python -m products.signals.dags.inbox_ranking.multihead [--partition YYYY-MM-DD] [--output results.json]

The cache must hold the state, labels and report embeddings tables. The title embeddings are never
read, so the run holds one set of vectors.
"""

import os
import argparse
from pathlib import Path

import django

DEFAULT_CACHE_DIR = Path(os.environ.get("INBOX_RANKING_SYNC_DIR", Path.home() / ".cache/posthog/inbox_ranking"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--partition", help="the training day D; defaults to the newest day with every table cached")
    parser.add_argument("--lookback-days", type=int, help="defaults to INBOX_RANKING_TRAINING_LOOKBACK_DAYS")
    parser.add_argument("--holdout-days", type=int, help="defaults to INBOX_RANKING_TRAINING_HOLDOUT_DAYS")
    parser.add_argument("--ablation", choices=["report", "project", "both"], default="both")
    parser.add_argument("--skip-champion", action="store_true", help="skip the XGBoost champion recipe refit")
    parser.add_argument("--projection-dim", type=int, default=64)
    parser.add_argument("--trunk-dim", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--weight-decay", type=float, default=1e-2)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, help="also write the scores as JSON here")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # The run reads only the disk cache. Without this, setup in DEBUG resolves a self-capture team
    # from Postgres, so the script would need the dev stack up.
    os.environ.setdefault("OPT_OUT_CAPTURE", "1")
    django.setup()
    # The dataset and training modules load Django models at import time, so they wait for setup.
    from products.signals.dags.inbox_ranking.multihead.local import run_from_cache  # noqa: PLC0415

    run_from_cache(arguments)


if __name__ == "__main__":
    main()
