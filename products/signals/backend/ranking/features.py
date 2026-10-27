"""Feature universes for the report-ranking model.

A `FeatureSet` is one universe: its name, its schema version, its ordered feature names, the
report-state columns it reads, and `build_matrix`, which turns a frame of those rows into the
matrix. A model records the set it was fit on in its `metadata.json`, so a run can hold several
sets at once: the examples Parquet, the training matrix and the scoring matrix are all built per
set, and a model whose declared set this build cannot produce is left unscored.

Three sets live here. `report_embeddings` is the report's combined-text embedding vector, and
`report_embeddings_priority` is that vector plus the report's priority, one column per level. They
are the served contract: training (`products/signals/dags/inbox_ranking/training/`) and serving
(the scoring sweep in this package) build features through the same `build_matrix`, so the model's
`feature_names` match the serving matrix by construction. The sweep reads the vector at scoring
time, and reads the latest priority judgment only for a model whose set declares the `priority`
state column. `report_embeddings_priority_sources` adds the source products of the report's signals.
Only an experiment family trains on it, and the sweep cannot build it yet.
"""

import abc
import datetime
from collections.abc import Mapping, Sequence
from types import MappingProxyType

import numpy as np
import pandas as pd

from posthog.dataclasses import frozen

# Side inputs a set may read next to the report-state rows, keyed by name and indexed by
# report_id.
Extras = Mapping[str, pd.DataFrame]
NO_EXTRAS: Extras = MappingProxyType({})

# The report vector, under this key in `extras`: the dataset dag's `inbox_report_embeddings`
# snapshot, indexed by report_id, with the vector in `EMBEDDING_COLUMN` and the moment that vector
# landed in `EMBEDDING_INSERTED_AT_COLUMN`.
REPORT_EMBEDDINGS_EXTRA = "report_embeddings"
EMBEDDING_COLUMN = "embedding_small"
EMBEDDING_INSERTED_AT_COLUMN = "embedding_inserted_at"
# The width of text-embedding-3-small-1536, the model the report documents are embedded with. A
# row whose vector is a different length is not this model's, so it is treated as missing.
EMBEDDING_DIMENSIONS = 1536
# Position order, so `emb_i` is the vector's ith component in every matrix an embedding set builds.
EMBEDDING_FEATURE_NAMES = tuple(f"emb_{index}" for index in range(EMBEDDING_DIMENSIONS))

# The report-state column that holds the report's latest priority judgment as of the moment, and
# the levels a set encodes it with.
PRIORITY_COLUMN = "priority"
PRIORITY_LEVELS = ("P0", "P1", "P2", "P3", "P4")

# The source products of a report's signals, under this key in `extras`: the metadata columns of the
# dataset dag's `inbox_signal_embeddings` emission log, one row per signal emission, with the moment
# the emission landed in `SIGNAL_INSERTED_AT_COLUMN`.
REPORT_SOURCES_EXTRA = "report_sources"
SIGNAL_INSERTED_AT_COLUMN = "embedding_inserted_at"
REPORT_SOURCES_COLUMNS = (
    "team_id",
    "signal_id",
    "report_id",
    "source_product",
    "is_deleted",
    SIGNAL_INSERTED_AT_COLUMN,
)
# A fixed vocabulary, so a new source product does not change the feature names. A product outside
# it sets `source_other`.
SOURCE_PRODUCTS = (
    "signals_scout",
    "error_tracking",
    "session_replay",
    "replay_vision",
    "conversations",
    "zendesk",
    "github",
    "linear",
    "jira",
    "llm_analytics",
    "logs",
    "health_checks",
    "signals_check",
)
SOURCE_FEATURE_NAMES = (*(f"source_{product}" for product in SOURCE_PRODUCTS), "source_other")

# The team's project-vector kinds, in the order a network that reads them takes them. The dataset
# dag's `inbox_project_vectors` writes one row per (team, kind), and the training and serving
# inputs both read these names, so the two sides cannot order the kinds differently.
PROJECT_VECTOR_KINDS = ("typical", "open", "action", "dismiss")
# Below this many reports, a kind's mean is mostly one report's text, so the row keeps an all-zero
# vector and the kind has no history.
MIN_PROJECT_HISTORY_REPORTS = 5

# How many rows one report contributes to a head's examples. The default is `birth`, one row per
# report at the snapshot of the day it was created; `examples.py` holds the reasoning.
# `scoring_moment` is one row per (report, snapshot), and `report` is the first snapshot of the
# window where the report is a usable moment. Both stay selectable for the re-scoring families.
BIRTH_GRAIN = "birth"
SCORING_MOMENT_GRAIN = "scoring_moment"
REPORT_GRAIN = "report"


class FeatureSet(abc.ABC):
    """One feature universe a model can be fit on and scored with.

    `state_columns` are the report-state columns `build_matrix` reads, and `extras_keys` the side
    inputs it needs next to them. The caller always adds `age_hours`, so a set may read that
    without declaring it. `example_grain` defaults to one birth-day row per report so the fit does
    not weight reports by their lifetime. Daily snapshots remain available for the scoring-moment
    and report grains. `max_examples_per_head` bounds the population for wide sets.
    """

    name: str
    schema_version: int
    feature_names: tuple[str, ...]
    state_columns: tuple[str, ...]
    extras_keys: tuple[str, ...] = ()
    example_grain: str = BIRTH_GRAIN
    # Rows one head's examples may keep, or None for every row the grain produces.
    max_examples_per_head: int | None = None

    @abc.abstractmethod
    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        """The matrix for `rows`, one column per name in `feature_names` order.

        `rows` carries the state columns the set declared plus `age_hours`, indexed by report_id.
        `extras` carries the side inputs a set needs beyond report state. `as_of` is the moment
        being scored, so a set reading a side input that changes over a report's life takes the
        value the report had then rather than the latest one.
        """

    def buildable(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.Series:
        """True for each row of `rows` this set can build a real vector for at `as_of`; every row by
        default.

        A set reading a side input has rows it cannot cover, and the example builder keeps only the
        rows that are True, so a training row never carries an all-missing vector. The scorer does
        not filter on this: every family scores the whole pool, or the grades stop being paired.
        """
        return pd.Series(True, index=rows.index)

    def missing_extras(self, extras: Extras) -> tuple[str, ...]:
        """The side inputs this set declares that `extras` does not carry."""
        return tuple(key for key in self.extras_keys if key not in extras)


class ReportEmbeddingsFeatureSet(FeatureSet):
    """One text rendering's embedding vector, and nothing else, at one example per report.

    Parameterized by the `extras` key it reads, so another rendering is a second instance rather
    than a second class, and shares this width, this grain and this row budget by construction. A
    set reads its own key only, and never falls back to another rendering's vector.

    Two modelling calls this set records, both open questions on the issue that asked for it
    (posthog#98243):

    Embedding only, no age. Age is the whole signal of the `recency_auc` line the unseen read
    already reports next to every grade, so leaving it out keeps the uplift claim clean: a gap to
    that line is content, not recency. A set that mixes the two is a third family, not a variant.

    One example per report, not one per scoring moment. A day's newborns over the whole lookback,
    times 1536 floats, is gigabytes of Parquet per partition and more than the training pod holds,
    which is what rules the moment grain out at this width. The default birth grain gives that.
    `max_examples_per_head` bounds what is left by dropping the oldest report-creation days; the
    lookback stays the training job's, so positives accrue over the whole window until the budget binds.

    Vectors arrive through `extras`, from the rendering's own dt=D snapshot, which holds the
    latest vector per report. A report is re-embedded whenever its text changes, and the
    summary workflow and each re-research run rewrite it, so the latest vector can postdate the
    moment being built. `as_of` is therefore load-bearing rather than a nicety: a moment takes the
    vector only when that vector had already landed, so a report whose birth-day snapshot holds
    only a later vector is no example at all, and at the report grain it moves to the first
    snapshot where the vector was its own. Without the check the family would train on text that
    did not exist when the report was supposedly scored, which is the one thing that would
    invalidate the comparison this family exists for.

    A report the snapshot has no vector for at all is not buildable either: the source table's TTL
    runs from report creation, so a long-lived report loses its vector while still live, and an
    all-missing row would teach the booster nothing but the base rate.
    """

    schema_version = 1
    feature_names = EMBEDDING_FEATURE_NAMES
    state_columns: tuple[str, ...] = ()
    # 1536 float32 columns, so a head's training matrix scales with this. Sized above the largest
    # head over the 90-day lookback, so the budget is a memory guard and does not trim the window.
    # The budget cuts the oldest report-creation days, so a budget that binds starves the rare
    # heads of the positives the longer lookback adds.
    max_examples_per_head = 250_000

    def __init__(self, *, name: str, extras_key: str) -> None:
        self.name = name
        self.extras_keys = (extras_key,)

    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        vectors = self._aligned_vectors(rows, extras, as_of)
        buildable = self._is_vector(vectors).to_numpy()
        matrix = np.full((len(rows), EMBEDDING_DIMENSIONS), np.nan, dtype=np.float32)
        if buildable.any():
            matrix[buildable] = np.vstack(vectors.to_numpy()[buildable])
        # The vector columns, not `feature_names`: a subclass adds columns after these.
        return pd.DataFrame(matrix, index=rows.index, columns=list(EMBEDDING_FEATURE_NAMES))

    def buildable(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.Series:
        return self._is_vector(self._aligned_vectors(rows, extras, as_of))

    def _aligned_vectors(self, rows: pd.DataFrame, extras: Extras, as_of: datetime.datetime | None) -> pd.Series:
        """The vector per row of `rows`: a missing value where the snapshot holds none, and where it
        holds one that landed after `as_of`.

        A vector with no landing time is dropped rather than trusted, because the check cannot be
        made for it.
        """
        vectors = extras.get(self.extras_keys[0])
        if vectors is None or EMBEDDING_COLUMN not in vectors:
            return pd.Series(None, index=rows.index, dtype=object)
        aligned = vectors[EMBEDDING_COLUMN].reindex(rows.index)
        if as_of is None:
            return aligned
        if EMBEDDING_INSERTED_AT_COLUMN not in vectors:
            raise ValueError(
                f"the {self.extras_keys[0]} side input needs {EMBEDDING_INSERTED_AT_COLUMN} to be read as of a moment"
            )
        landed = pd.to_datetime(vectors[EMBEDDING_INSERTED_AT_COLUMN].reindex(rows.index), utc=True)
        return aligned.where(landed.notna() & (landed <= as_of))

    @staticmethod
    def _is_vector(vectors: pd.Series) -> pd.Series:
        # An isinstance check rather than a null check: `reindex` fills a missing row with NaN,
        # which is neither None nor a vector, and a wrong-length row is another model's.
        return vectors.map(
            lambda vector: isinstance(vector, list | np.ndarray) and len(vector) == EMBEDDING_DIMENSIONS
        ).astype(bool)


class ReportEmbeddingsPriorityFeatureSet(ReportEmbeddingsFeatureSet):
    """The report vector, then the report's priority as one column per level in `PRIORITY_LEVELS`.

    The priority comes from the `priority` state column: the dataset dag cuts it at each snapshot
    from the latest priority judgment, and the scorer reads the latest judgment at scoring time. No
    judgment, or a value outside `PRIORITY_LEVELS`, sets every level column to zero. `buildable` is
    the parent's, so this set keeps the same rows as `report_embeddings`.
    """

    schema_version = 1
    feature_names = (*EMBEDDING_FEATURE_NAMES, *(f"priority_{level}" for level in PRIORITY_LEVELS))
    state_columns = (PRIORITY_COLUMN,)

    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        # A missing column must not read as "no priority" on every row: the model would then score
        # every report as unjudged and nothing would say so.
        if PRIORITY_COLUMN not in rows:
            raise ValueError(f"the {self.name} feature set needs the {PRIORITY_COLUMN} column")
        matrix = super().build_matrix(rows, extras, as_of=as_of)
        priorities = rows[PRIORITY_COLUMN]
        for level in PRIORITY_LEVELS:
            matrix[f"priority_{level}"] = (priorities == level).to_numpy(dtype=np.float32)
        return matrix


class ReportEmbeddingsPrioritySourcesFeatureSet(ReportEmbeddingsPriorityFeatureSet):
    """The priority set, then the source products of the report's signals as of the moment.

    One column per product in `SOURCE_PRODUCTS`, `source_other` for any other or a missing product,
    `source_count` for the number of distinct products, and `has_sources`. The signals come from the
    `REPORT_SOURCES_EXTRA` side input, an emission log with one row per signal emission. A moment
    reads only the emissions inserted at or before it, takes the latest emission per
    (team_id, signal_id), and drops a signal whose latest emission is a retraction. A signal can
    move to another report when it is regrouped, so the report comes from that latest emission.

    The impression labels also carry a `source_products` column, but it holds the value of the
    latest impression, so it can postdate the moment. This set never reads it.

    A report with no live signal at the moment gets zero in every source column, `has_sources`
    included. `buildable` is the parent's, so this set keeps the same rows as its baseline.
    """

    schema_version = 1
    feature_names = (
        *ReportEmbeddingsPriorityFeatureSet.feature_names,
        *SOURCE_FEATURE_NAMES,
        "source_count",
        "has_sources",
    )

    def __init__(self, *, name: str, extras_key: str, sources_key: str) -> None:
        super().__init__(name=name, extras_key=extras_key)
        self.extras_keys = (extras_key, sources_key)

    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        if as_of is None:
            raise ValueError(f"the {self.name} feature set reads its sources only as of a moment")
        matrix = super().build_matrix(rows, extras, as_of=as_of)
        sources = self._sources_as_of(extras[self.extras_keys[1]], rows.index, as_of)
        for column in (*SOURCE_FEATURE_NAMES, "source_count", "has_sources"):
            matrix[column] = sources[column].to_numpy(dtype=np.float32)
        return matrix

    @staticmethod
    def _sources_as_of(signals: pd.DataFrame, report_ids: pd.Index, as_of: datetime.datetime) -> pd.DataFrame:
        known = signals.loc[signals[SIGNAL_INSERTED_AT_COLUMN] <= as_of]
        latest = known.sort_values(SIGNAL_INSERTED_AT_COLUMN, kind="stable").drop_duplicates(
            ["team_id", "signal_id"], keep="last"
        )
        live = latest.loc[~latest["is_deleted"].astype(bool) & latest["report_id"].isin(report_ids)]
        product = live["source_product"].where(live["source_product"].isin(SOURCE_PRODUCTS), "other")
        one_hot = (
            pd.crosstab(live["report_id"], "source_" + product.astype(str))
            .clip(upper=1)
            .reindex(index=report_ids, columns=list(SOURCE_FEATURE_NAMES), fill_value=0)
        )
        # A missing product counts as one source of its own, so `has_sources` implies a count of 1 or more.
        distinct = live["source_product"].fillna("").groupby(live["report_id"]).nunique()
        one_hot["source_count"] = distinct.reindex(report_ids, fill_value=0).to_numpy()
        one_hot["has_sources"] = (one_hot["source_count"] > 0).astype(int).to_numpy()
        return one_hot


REPORT_EMBEDDINGS_FEATURE_SET = ReportEmbeddingsFeatureSet(name="report_embeddings", extras_key=REPORT_EMBEDDINGS_EXTRA)
REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET = ReportEmbeddingsPriorityFeatureSet(
    name="report_embeddings_priority", extras_key=REPORT_EMBEDDINGS_EXTRA
)
REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET = ReportEmbeddingsPrioritySourcesFeatureSet(
    name="report_embeddings_priority_sources", extras_key=REPORT_EMBEDDINGS_EXTRA, sources_key=REPORT_SOURCES_EXTRA
)

# Every set this build can produce, by name. A model that names a set absent from here cannot be
# scored, the same way a model whose feature names have moved on cannot.
FEATURE_SETS: Mapping[str, FeatureSet] = MappingProxyType(
    {
        REPORT_EMBEDDINGS_FEATURE_SET.name: REPORT_EMBEDDINGS_FEATURE_SET,
        REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET.name: REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
        REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET.name: REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
    }
)


@frozen
class ProjectInputs:
    """The project vectors of some teams, one row per team in the order the caller asked for."""

    # (teams, kinds, EMBEDDING_DIMENSIONS) float32, in `PROJECT_VECTOR_KINDS` order. All zero where
    # the team has no row for the kind or its history is too thin.
    vectors: np.ndarray
    # (teams, kinds) float32, 1.0 where the kind had at least `MIN_PROJECT_HISTORY_REPORTS` reports.
    has_history: np.ndarray


def project_inputs(project_vectors: pd.DataFrame, team_ids: Sequence[int]) -> ProjectInputs:
    """The project vectors of `team_ids` from one day of `inbox_project_vectors`.

    `project_vectors` carries the `team_id`, `kind`, `vector` and `n_reports` columns of that table.
    Training and serving both build the network's `project` and `has_history` inputs here, so a
    team without a row, a kind without a row and a thin kind read the same on both sides.
    """
    position = {int(team_id): index for index, team_id in enumerate(team_ids)}
    vectors = np.zeros((len(team_ids), len(PROJECT_VECTOR_KINDS), EMBEDDING_DIMENSIONS), dtype=np.float32)
    has_history = np.zeros((len(team_ids), len(PROJECT_VECTOR_KINDS)), dtype=np.float32)
    for team_id, kind, vector, n_reports in zip(
        project_vectors["team_id"],
        project_vectors["kind"],
        project_vectors["vector"],
        project_vectors["n_reports"],
        strict=True,
    ):
        team = position.get(int(team_id))
        if team is None or kind not in PROJECT_VECTOR_KINDS:
            continue
        kind_index = PROJECT_VECTOR_KINDS.index(kind)
        vectors[team, kind_index] = vector
        has_history[team, kind_index] = float(int(n_reports) >= MIN_PROJECT_HISTORY_REPORTS)
    return ProjectInputs(vectors=vectors, has_history=has_history)


def feature_set_by_name(name: str | None) -> FeatureSet | None:
    """The named set, or None when the name is absent or this build cannot produce it."""
    return None if name is None else FEATURE_SETS.get(name)
