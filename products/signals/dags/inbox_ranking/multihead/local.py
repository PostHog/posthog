"""Read the prototype's inputs from the disk cache `bin/sync_snapshots_local.sh` fills.

The cache mirrors the bucket layout below the prefix (`<table>/v1/dt=D/part-00000.parquet`), so
the training dag's own `load_snapshots` reads it through a store that answers `get_object` from disk.
"""

import io
import json
import argparse
import datetime
import dataclasses
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.features import (
    EMBEDDING_COLUMN,
    EMBEDDING_INSERTED_AT_COLUMN,
    REPORT_EMBEDDINGS_EXTRA,
    Extras,
)
from products.signals.dags.inbox_ranking.common import DATASET_VERSION, PARQUET_PART_NAME
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_TABLE, LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.dataset.project_vectors import EMBEDDING_COLUMNS, LABEL_COLUMNS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig
from products.signals.dags.inbox_ranking.multihead.prototype import (
    ABLATIONS,
    REPORT_ONLY,
    WITH_PROJECT_VECTORS,
    format_scores,
    run_prototype,
)
from products.signals.dags.inbox_ranking.training.dag import load_snapshots, snapshot_dates
from products.signals.dags.inbox_ranking.training.examples import Snapshot, drop_without_training_consent

_PREFIX = "local"
_TABLES = (STATE_TABLE, LABELS_TABLE, EMBEDDINGS_TABLE)


class LocalSnapshotStore:
    """Answers the `get_object` calls of the dag's readers from the disk cache."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        path = self.root / Key.removeprefix(f"{_PREFIX}/")
        if not path.is_file():
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": str(path)}}, "GetObject")
        return {"Body": io.BytesIO(path.read_bytes())}


def partition_path(root: Path, table: str, day: datetime.date) -> Path:
    return root / table / DATASET_VERSION / f"dt={day.isoformat()}" / PARQUET_PART_NAME


def newest_cached_partition(root: Path) -> datetime.date:
    """The newest day for which the state, labels and report embeddings are all cached."""
    days: set[datetime.date] | None = None
    for table in _TABLES:
        present = {
            datetime.date.fromisoformat(path.parent.name.removeprefix("dt="))
            for path in (root / table / DATASET_VERSION).glob(f"dt=*/{PARQUET_PART_NAME}")
        }
        days = present if days is None else days & present
    if not days:
        raise SystemExit(
            f"no day in {root} has {', '.join(_TABLES)} cached; "
            "run bin/sync_snapshots_local.sh with INBOX_RANKING_SYNC_EMBEDDINGS=1"
        )
    return max(days)


def consenting_snapshots(
    snapshots: dict[datetime.date, Snapshot], newest: datetime.date
) -> dict[datetime.date, Snapshot]:
    """`snapshots` without the reports of teams absent from the newest state snapshot.

    The training dag filters on `training_consent_team_ids()`, which reads the production database
    a local run cannot reach. The newest state snapshot holds only teams that allowed AI training on
    that day, so its teams stand in for the list and an opt-out still reaches older partitions.
    """
    state = snapshots[newest].state
    team_ids = frozenset(int(team_id) for team_id in state["report_team_id"].dropna())
    kept, _ = drop_without_training_consent(snapshots, team_ids)
    return kept


def report_vectors(embeddings: pa.Table) -> Extras:
    """The `report_embeddings` side input, indexed by report_id."""
    vectors = (
        embeddings.select(["report_id", EMBEDDING_COLUMN, EMBEDDING_INSERTED_AT_COLUMN])
        .to_pandas()
        .set_index("report_id")
    )
    return {REPORT_EMBEDDINGS_EXTRA: vectors[~vectors.index.duplicated()]}


def run_from_cache(arguments: argparse.Namespace) -> None:
    root: Path = arguments.snapshots_dir.expanduser()
    day = datetime.date.fromisoformat(arguments.partition) if arguments.partition else newest_cached_partition(root)
    lookback_days = arguments.lookback_days or settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS
    holdout_days = arguments.holdout_days or settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS
    ablations = {"report": (REPORT_ONLY,), "project": (WITH_PROJECT_VECTORS,), "both": ABLATIONS}[arguments.ablation]

    dates = snapshot_dates(day.isoformat(), lookback_days)
    snapshots = load_snapshots(LocalSnapshotStore(root), "", _PREFIX, dates, required=day)
    snapshots = consenting_snapshots(snapshots, day)
    print(f"dt={day}: {len(snapshots)} of {len(dates)} snapshots cached, holdout {holdout_days} days")  # noqa: T201

    embeddings_path = partition_path(root, EMBEDDINGS_TABLE, day)
    if not embeddings_path.is_file():
        raise SystemExit(f"{embeddings_path} is missing; sync with INBOX_RANKING_SYNC_EMBEDDINGS=1")
    # One embeddings snapshot serves every moment, as in the training dag, and the project vectors
    # read the same table, so a single set of vectors is in memory.
    embeddings = pq.read_table(embeddings_path, columns=list(EMBEDDING_COLUMNS))
    labels = None
    if WITH_PROJECT_VECTORS in ablations:
        labels = pq.read_table(partition_path(root, LABELS_TABLE, day), columns=list(LABEL_COLUMNS))

    config = NetworkConfig(
        projection_dim=arguments.projection_dim,
        trunk_dim=arguments.trunk_dim,
        dropout=arguments.dropout,
        weight_decay=arguments.weight_decay,
        learning_rate=arguments.learning_rate,
        epochs=arguments.epochs,
        batch_size=arguments.batch_size,
        seed=arguments.seed,
    )
    result = run_prototype(
        snapshots,
        report_vectors(embeddings),
        labels=labels,
        embeddings=embeddings,
        holdout_days=holdout_days,
        config=config,
        ablations=ablations,
        champion=not arguments.skip_champion,
    )
    print(f"network train rows: {result.network_train_rows}")  # noqa: T201
    print(format_scores(result.scores))  # noqa: T201
    if arguments.output:
        payload = {
            "partition": day.isoformat(),
            "lookback_days": lookback_days,
            "holdout_days": holdout_days,
            "config": dataclasses.asdict(config),
            **result.as_dict(),
        }
        arguments.output.write_text(json.dumps(payload, indent=2, default=str))
