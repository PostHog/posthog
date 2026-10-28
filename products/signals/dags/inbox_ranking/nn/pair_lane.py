"""The experiments job's pair lane: fit and grade a pair-grain experiment, without torch at import.

A pair-grain family (`grain="pair"` in `training/families.py`) trains on the day's
`inbox_ranking_nn_pair_examples` object, one row per (report example, impressed user), and never
rebuilds it. A pair reads its report's input as the report lane builds it, from the report's row of
the day's `inbox_ranking_nn_examples` object, and its team's project vectors as of the start of its
birth day. The experiment and its pair baseline fit with each of `EXPERIMENT_SEEDS` on the same train
pairs and are graded on the same holdout pairs.

The reference is a report-grain serving family. For each seed it is fit on the report rows of the
pair train days, at report grain with every `nn` head, and each holdout pair takes its report's
score. That answers "better than a report-level score" on the same days without loading the served
model, and the read stays paired on seeds. The reference is fit first and its report inputs are
dropped before the pair inputs are built, so the two matrices are never held at once.

A partition without pair examples, report examples or the dt=D snapshots keeps what it holds.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import dagster

from posthog import settings

from products.signals.backend.ranking.features import Extras, FeatureSet
from products.signals.dags.inbox_ranking.common import partition_object_key, read_parquet_if_exists
from products.signals.dags.inbox_ranking.dataset.project_vectors import VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkInputs
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable, project_context, report_matrix
from products.signals.dags.inbox_ranking.nn.dag import (
    EXPERIMENT_SEEDS,
    NETWORK_CONFIG,
    NN_EXAMPLES_TABLE,
    DayInputs,
    _day_inputs,
    write_candidate,
)
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES, NN_HEADS, examples_from_arrow, network_inputs
from products.signals.dags.inbox_ranking.nn.model import family_heads, network_recipe
from products.signals.dags.inbox_ranking.nn.pair_grade import pair_vs_baseline_block
from products.signals.dags.inbox_ranking.nn.pairs import (
    NN_PAIR_EXAMPLES_TABLE,
    PAIR_EXAMPLES_SCHEMA_VERSION,
    PAIR_HORIZON_DAYS,
)
from products.signals.dags.inbox_ranking.training.dag import check_recipe
from products.signals.dags.inbox_ranking.training.families import MODEL_FAMILIES, ModelFamily
from products.signals.dags.inbox_ranking.training.side_inputs import load_side_inputs

# The pair labels' horizon and the pair object's schema, in a pair family's recipe.
PAIR_SETTINGS: dict[str, Any] = {
    "label_horizon_days": PAIR_HORIZON_DAYS,
    "examples_schema_version": PAIR_EXAMPLES_SCHEMA_VERSION,
}
_REPORT_KEY = ["report_id", "snapshot_date"]
_PAIR_COLUMNS = [
    "report_id",
    "snapshot_date",
    "report_team_id",
    "user_distinct_id",
    "prior_views",
    "is_suggested_reviewer",
]


def pair_example_table(pairs: pd.DataFrame, report_rows: pd.DataFrame, heads: Sequence[str]) -> ExampleTable:
    """One row per pair, with labels and holdout flags in `heads` order.

    A pair takes the state columns of its report's examples row (such as `priority`), so a feature
    set builds its report input as the report lane does. A pair whose report has no examples row is
    dropped. Every head of a pair shares the report's holdout flag.
    """
    state = report_rows.drop(columns=["report_team_id"])
    merged = pairs.merge(state, on=_REPORT_KEY, how="inner", validate="many_to_one")
    rows = merged[[*_PAIR_COLUMNS, *(c for c in state.columns if c not in _REPORT_KEY)]].reset_index(drop=True)
    labels = np.column_stack([merged[f"{head}_label"].to_numpy(dtype=np.float32) for head in heads])
    holdout = np.repeat(merged["holdout"].to_numpy(dtype=bool)[:, None], len(heads), axis=1)
    return ExampleTable(
        rows=rows, labels=labels.reshape(len(rows), len(heads)), holdout=holdout.reshape(len(rows), len(heads))
    )


def report_positions(report_rows: pd.DataFrame, pair_rows: pd.DataFrame) -> np.ndarray:
    """The position of each pair's report row in `report_rows`, -1 where it has none."""
    reports = pd.MultiIndex.from_frame(report_rows[_REPORT_KEY])
    return reports.get_indexer(pd.MultiIndex.from_frame(pair_rows[_REPORT_KEY]))


def broadcast_report_scores(
    report_scores: np.ndarray, positions: np.ndarray, report_heads: Sequence[str], pair_heads: Sequence[str]
) -> np.ndarray:
    """(pairs, pair heads) scores: every pair takes its report's score of the same head, NaN where
    the pair's report has no row."""
    columns = [list(report_heads).index(head) for head in pair_heads]
    scores = np.full((len(positions), len(pair_heads)), np.nan, dtype=np.float32)
    found = positions >= 0
    scores[found] = report_scores[positions[found]][:, columns]
    return scores


def reference_train_rows(report_table: ExampleTable, pair_table: ExampleTable) -> np.ndarray:
    """The report rows the reference fits on: the report lane's train rows born on a pair train day.
    The report train rows are in no head's holdout, so no holdout pair's report is among them."""
    days = set(pair_table.rows["snapshot_date"].iloc[pair_table.network_train_rows()])
    train = report_table.network_train_rows()
    return train[report_table.rows["snapshot_date"].iloc[train].isin(days).to_numpy()]


def pair_report_matrix(rows: pd.DataFrame, extras: Extras, feature_set: FeatureSet) -> np.ndarray:
    """The report input of every pair. Built once per report moment, then repeated for its pairs."""
    reports = rows.drop_duplicates(_REPORT_KEY).reset_index(drop=True)
    return report_matrix(reports, extras, feature_set)[report_positions(reports, rows)]


def pair_network_inputs(table: ExampleTable, extras: Extras, day: DayInputs, feature_set: FeatureSet) -> NetworkInputs:
    return NetworkInputs(
        reports=pair_report_matrix(table.rows, extras, feature_set),
        context=project_context(table.rows, day.labels, day.embeddings),
    )


def _family(name: str | None) -> ModelFamily | None:
    return next((family for family in MODEL_FAMILIES if family.name == name), None) if name is not None else None


def _skipped(context: dagster.AssetExecutionContext, message: str) -> dict[str, dagster.MetadataValue]:
    context.log.warning(message)
    return {"skipped": dagster.MetadataValue.bool(True)}


def reference_scores(
    report_table: ExampleTable,
    pair_table: ExampleTable,
    reference: ModelFamily,
    extras: Extras,
    day: DayInputs,
    heads: Sequence[str],
) -> list[np.ndarray]:
    """Per seed, the reference fit on the report rows of the pair train days, its report scores
    broadcast to every pair."""
    from products.signals.dags.inbox_ranking.nn.train import (  # noqa: PLC0415 — keeps torch off the location's import path
        seed_scores,
    )

    inputs = network_inputs(report_table, extras, day.labels, day.embeddings, reference.feature_set)
    positions = report_positions(report_table.rows, pair_table.rows)
    scores = seed_scores(
        report_table,
        inputs,
        NN_HEADS,
        NETWORK_CONFIG,
        EXPERIMENT_SEEDS,
        train_rows=reference_train_rows(report_table, pair_table),
    )
    return [broadcast_report_scores(seed, positions, NN_HEAD_NAMES, heads) for seed in scores]


def train_pair_candidate(
    context: dagster.AssetExecutionContext, client, bucket: str, partition_key: str, family: ModelFamily
) -> dict[str, dagster.MetadataValue]:
    """Fit the day's network for the pair-grain `family`, grade it against its pair baseline and its
    reference, write its graphs and `metadata.json` under `<model_name>/dt=D/`, and return the asset
    metadata."""
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    pairs = read_parquet_if_exists(client, bucket, partition_object_key(prefix, NN_PAIR_EXAMPLES_TABLE, partition_key))
    if pairs is None:
        return _skipped(
            context,
            f"no {NN_PAIR_EXAMPLES_TABLE} for dt={partition_key}; {family.name} keeps this partition as it stands. "
            f"Run inbox_ranking_nn_pair_examples_job for dt={partition_key}",
        )
    report_arrow = read_parquet_if_exists(
        client, bucket, partition_object_key(prefix, NN_EXAMPLES_TABLE, partition_key)
    )
    if report_arrow is None:
        return _skipped(
            context, f"no nn examples for dt={partition_key}; {family.name} keeps this partition as it stands"
        )
    examples = examples_from_arrow(report_arrow)
    del report_arrow
    pair_frame = pairs.to_pandas()
    del pairs
    table = pair_example_table(pair_frame, examples.table.rows, family.heads)
    without_report = len(pair_frame) - len(table.rows)
    del pair_frame
    if without_report:
        context.log.warning(f"{without_report} pairs of dt={partition_key} have no report examples row; dropped")

    baseline, reference = _family(family.baseline), _family(family.reference)
    for arm in (family, baseline, reference):
        if arm is None:
            continue
        rows = examples.table.rows if arm is reference else table.rows
        missing = [column for column in arm.feature_set.state_columns if column not in rows]
        if missing:
            return _skipped(
                context,
                f"the nn examples for dt={partition_key} have no {', '.join(missing)} column for {arm.name}; "
                f"{family.name} keeps this partition as it stands",
            )
    day = _day_inputs(context, client, bucket, prefix, partition_key)
    if day is None:
        return {"skipped": dagster.MetadataValue.bool(True)}
    arms = [arm for arm in (family, baseline, reference) if arm is not None]
    wanted = sorted({key for arm in arms for key in arm.feature_set.missing_extras(day.extras)})
    extras = {**day.extras, **load_side_inputs(client, bucket, prefix, partition_key, wanted)}
    missing_extras = sorted({key for arm in arms for key in arm.feature_set.missing_extras(extras)})
    if missing_extras:
        return _skipped(
            context,
            f"no {', '.join(missing_extras)} side input for dt={partition_key}; {family.name} keeps this partition "
            "as it stands",
        )
    # Pair inputs always carry the project context, so the graphs take every project-vector kind.
    check_recipe(
        client,
        bucket,
        prefix,
        family.name,
        partition_key,
        network_recipe(family, NETWORK_CONFIG, VECTOR_KINDS, PAIR_SETTINGS),
    )

    from products.signals.dags.inbox_ranking.nn.train import (  # noqa: PLC0415 — keeps torch off the location's import path
        seed_scores,
        train_network,
    )

    heads = family_heads(family)
    has_train_pairs = len(table.network_train_rows()) > 0
    reference_seed_scores = None
    if reference is not None and has_train_pairs:
        reference_seed_scores = reference_scores(examples.table, table, reference, extras, day, family.heads)
    inputs = pair_network_inputs(table, extras, day, family.feature_set)
    baseline_reports = pair_report_matrix(table.rows, extras, baseline.feature_set) if baseline is not None else None
    del day

    trained = train_network(table, inputs, heads, NETWORK_CONFIG)
    vs_baseline = None
    if has_train_pairs:
        vs_baseline = pair_vs_baseline_block(
            table,
            family.heads,
            baseline=family.baseline,
            reference=family.reference,
            seeds=EXPERIMENT_SEEDS,
            experiment_scores=seed_scores(table, inputs, heads, NETWORK_CONFIG, EXPERIMENT_SEEDS),
            baseline_scores=(
                seed_scores(
                    table,
                    NetworkInputs(reports=baseline_reports, context=inputs.context),
                    heads,
                    NETWORK_CONFIG,
                    EXPERIMENT_SEEDS,
                )
                if baseline_reports is not None
                else None
            ),
            reference_scores=reference_seed_scores,
        )
    metadata = write_candidate(
        context,
        client,
        bucket,
        partition_key,
        family,
        trained,
        windows={name: window for name, window in examples.windows.items() if name in family.heads},
        vs_baseline=vs_baseline,
        pair_settings=PAIR_SETTINGS,
    )
    return {
        **metadata,
        "pair_rows": dagster.MetadataValue.int(len(table.rows)),
        "pairs_without_report_row": dagster.MetadataValue.int(without_report),
    }
