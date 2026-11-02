"""The experiments job's pair lane: fit and grade a pair-grain experiment, without torch at import.

A pair-grain family (`grain="pair"` in `training/families.py`) trains on the day's
`inbox_ranking_nn_pair_examples` object, one row per (report example, impressed user), and never
rebuilds it. A pair reads its report's input as the report lane builds it, from the report's row of
the day's `inbox_ranking_nn_examples` object, and its team's project vectors as of the start of its
birth day. The experiment and its pair baseline fit with each of `EXPERIMENT_SEEDS` on the same train
pairs and are graded on the same holdout pairs.

A family on a pair set (`PairUserHistoryFeatureSet`) also reads the pair's user columns and the
user's history as offsets from the team's project vectors. Each arm builds its own inputs from the
pair rows: the report part is built once per report and repeated, but the user columns and offsets
are per pair, so two users of one report never share them. A set with `user_history` off gets zero
user columns and zero offsets, whatever the pair rows hold. The user vectors are rebuilt from the
dt=D interactions and embeddings snapshots through `pair_user_vectors`, on the history of teams with
training consent only, as the pair examples asset builds them.

The reference is a report-grain serving family. For each seed it is fit on the report rows of the
pair train days, at report grain with every `nn` head, and each holdout pair takes its report's
score. That answers "better than a report-level score" on the same days without loading the served
model, and the read stays paired on seeds. The reference is fit first and its report inputs are
dropped before the pair inputs are built, so the two matrices are never held at once.

A partition without pair examples, report examples, the dt=D snapshots or, for a family that reads
user history, the dt=D interactions snapshot keeps what it holds.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.compute as pc

from posthog import settings
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    PAIR_STATE_COLUMNS,
    USER_HISTORY_KINDS,
    USER_REPORTS_COLUMNS,
    Extras,
    FeatureSet,
    PairUserHistoryFeatureSet,
    user_offsets,
)
from products.signals.dags.inbox_ranking.common import partition_object_key, read_parquet_if_exists
from products.signals.dags.inbox_ranking.consent import training_consent_team_ids
from products.signals.dags.inbox_ranking.dataset.dag import USER_INTERACTIONS_TABLE
from products.signals.dags.inbox_ranking.dataset.project_vectors import USER_INTERACTION_COLUMNS, VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkInputs, ProjectContext, UserContext
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
from products.signals.dags.inbox_ranking.nn.model import family_heads, family_user_kinds, network_recipe
from products.signals.dags.inbox_ranking.nn.pair_grade import pair_vs_baseline_block
from products.signals.dags.inbox_ranking.nn.pairs import (
    NN_PAIR_EXAMPLES_TABLE,
    PAIR_EXAMPLES_SCHEMA_VERSION,
    PAIR_HORIZON_DAYS,
    pair_user_vectors,
    team_organizations,
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
# One user's history as of one birth day, read against one team's project vectors.
_USER_KEY = ["report_team_id", "user_distinct_id", "snapshot_date"]
_PAIR_COLUMNS = [
    "report_id",
    "snapshot_date",
    "report_team_id",
    "user_distinct_id",
    "prior_views",
    *PAIR_STATE_COLUMNS,
]


@frozen
class UserHistory:
    """What `pair_user_vectors` reads beside the embeddings snapshot."""

    # The dt=D `inbox_user_report_interactions` snapshot, only the rows of teams with training consent.
    interactions: pa.Table
    # Each consented team's organization, so a user's history stays inside one organization.
    organizations: Mapping[int, str]


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
    """The report input of every pair. The report part is built once per report moment, then
    repeated for its pairs. A pair set's user columns are built per pair after it."""
    reports = rows.drop_duplicates(_REPORT_KEY).reset_index(drop=True)
    report_set = feature_set.report_feature_set if isinstance(feature_set, PairUserHistoryFeatureSet) else feature_set
    report_part = report_matrix(reports, extras, report_set)
    positions = report_positions(reports, rows)
    if not isinstance(feature_set, PairUserHistoryFeatureSet):
        return report_part[positions]
    width = report_part.shape[1]
    matrix = np.empty((len(rows), len(feature_set.feature_names)), dtype=np.float32)
    matrix[:, :width] = report_part[positions]
    matrix[:, width:] = feature_set.pair_matrix(rows)
    return matrix


def user_context(
    rows: pd.DataFrame, project: ProjectContext, history: UserHistory, embeddings: pa.Table
) -> UserContext:
    """The user offsets each pair of `rows` reads: its own user's vectors as of the start of its birth
    day, minus its team's project vectors from `project` (`user_offsets`).

    One vector per (team, user, birth day), so two pairs of one user that day share it and two users
    of one report never do. A kind counts only when the pair's stored `user_<kind>_reports` says the
    user had a report of it, the same count the pair object records.
    """
    keys = rows[_USER_KEY].drop_duplicates()
    index = pd.MultiIndex.from_frame(keys).get_indexer(pd.MultiIndex.from_frame(rows[_USER_KEY]))
    first_rows = keys.index.to_numpy()
    vectors = pair_user_vectors(
        keys.reset_index(drop=True), history.interactions, embeddings, organizations=history.organizations
    )
    projects = project.index[first_rows]
    offsets = user_offsets(
        vectors,
        rows[list(USER_REPORTS_COLUMNS)].to_numpy(dtype=np.float32)[first_rows],
        project.vectors[projects],
        project.has_history[projects],
    )
    return UserContext(vectors=offsets, index=index.astype(np.int64))


def zero_user_context(rows: int) -> UserContext:
    """A user offset of zero for every row, one shared key, so the arm keeps the input shape and
    reads nothing of anyone's history."""
    vectors = np.zeros((1, len(USER_HISTORY_KINDS), EMBEDDING_DIMENSIONS), dtype=np.float32)
    return UserContext(vectors=vectors, index=np.zeros(rows, dtype=np.int64))


def pair_network_inputs(
    table: ExampleTable,
    extras: Extras,
    feature_set: FeatureSet,
    project: ProjectContext,
    history: UserHistory | None,
    embeddings: pa.Table,
) -> NetworkInputs:
    """One arm's inputs, built from the pair rows for `feature_set` alone. The project context is the
    team's and holds nothing personal, so the arms share it."""
    users = None
    if isinstance(feature_set, PairUserHistoryFeatureSet):
        if not feature_set.user_history:
            users = zero_user_context(len(table.rows))
        elif history is None:
            raise ValueError(f"the {feature_set.name} feature set needs the user history")
        else:
            users = user_context(table.rows, project, history, embeddings)
    return NetworkInputs(reports=pair_report_matrix(table.rows, extras, feature_set), context=project, users=users)


def load_user_history(client, bucket: str, prefix: str, partition_key: str) -> UserHistory | None:
    """The dt=D interactions snapshot of the teams with training consent, and their organizations;
    None when the snapshot is missing."""
    interactions = read_parquet_if_exists(
        client,
        bucket,
        partition_object_key(prefix, USER_INTERACTIONS_TABLE, partition_key),
        columns=list(USER_INTERACTION_COLUMNS),
    )
    if interactions is None:
        return None
    consent_team_ids = training_consent_team_ids()
    consented = pa.array(sorted(consent_team_ids), pa.int64())
    return UserHistory(
        interactions=interactions.filter(pc.is_in(interactions.column("report_team_id"), value_set=consented)),
        organizations=team_organizations(consent_team_ids),
    )


def _reads_user_history(family: ModelFamily | None) -> bool:
    return (
        family is not None
        and isinstance(family.feature_set, PairUserHistoryFeatureSet)
        and family.feature_set.user_history
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
    history = None
    if _reads_user_history(family) or _reads_user_history(baseline):
        history = load_user_history(client, bucket, prefix, partition_key)
        if history is None:
            return _skipped(
                context,
                f"no {USER_INTERACTIONS_TABLE} snapshot for dt={partition_key}; {family.name} reads user history "
                "and keeps this partition as it stands",
            )
    # Pair inputs always carry the project context, so the graphs take every project-vector kind.
    check_recipe(
        client,
        bucket,
        prefix,
        family.name,
        partition_key,
        network_recipe(
            family, NETWORK_CONFIG, VECTOR_KINDS, PAIR_SETTINGS, user_vector_kinds=family_user_kinds(family)
        ),
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
    project = project_context(table.rows, day.labels, day.embeddings)
    inputs = pair_network_inputs(table, extras, family.feature_set, project, history, day.embeddings)
    baseline_inputs = (
        pair_network_inputs(table, extras, baseline.feature_set, project, history, day.embeddings)
        if baseline is not None
        else None
    )
    del day, history

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
                seed_scores(table, baseline_inputs, heads, NETWORK_CONFIG, EXPERIMENT_SEEDS)
                if baseline_inputs is not None
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
    with_history = table.rows["prior_views"].to_numpy() > 0
    return {
        **metadata,
        "pair_rows": dagster.MetadataValue.int(len(table.rows)),
        "pair_users": dagster.MetadataValue.int(
            int(table.rows[["report_team_id", "user_distinct_id"]].drop_duplicates().shape[0])
        ),
        "pair_rows_with_prior_views": dagster.MetadataValue.int(int(with_history.sum())),
        "pairs_without_report_row": dagster.MetadataValue.int(without_report),
    }
