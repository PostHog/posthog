import datetime

import pytest

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.parquet as pq

from posthog import settings

from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    REPORT_EMBEDDINGS_EXTRA,
    REPORT_EMBEDDINGS_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
    REPORT_SOURCES_EXTRA,
)
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import SIGNAL_EMBEDDINGS_SCHEMA, SIGNAL_EMBEDDINGS_TABLE
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable, report_matrix
from products.signals.dags.inbox_ranking.nn import experiments
from products.signals.dags.inbox_ranking.nn.dag import NN_EXAMPLES_TABLE
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES
from products.signals.dags.inbox_ranking.nn.model import vs_baseline_block
from products.signals.dags.inbox_ranking.tests.test_training import _ModelStoreS3
from products.signals.dags.inbox_ranking.training import side_inputs
from products.signals.dags.inbox_ranking.training.families import NN_MODEL_NAME, ModelFamily, family_problems
from products.signals.dags.inbox_ranking.training.side_inputs import (
    SideInputError,
    SideInputLoader,
    load_side_inputs,
    rows_as_of,
)

PARTITION = "2026-10-20"
PREFIX = settings.INBOX_RANKING_DATASET_S3_PREFIX
SIDE_INPUT = "report_sources"


def _experiment(name: str, expires: datetime.date) -> ModelFamily:
    return ModelFamily(
        name=name,
        feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
        experiment=True,
        baseline=NN_MODEL_NAME,
        expires=expires,
    )


@pytest.mark.parametrize("examples_present", [True, False])
def test_an_expired_experiment_and_a_day_without_examples_train_nothing(monkeypatch, examples_present):
    trained: list[str] = []

    def train_candidate(context, client, bucket, partition_key, family):
        trained.append(family.name)
        return {"heads_trained": dagster.MetadataValue.int(3)}

    monkeypatch.setattr(experiments, "train_candidate", train_candidate)
    objects = {partition_object_key(PREFIX, NN_EXAMPLES_TABLE, PARTITION): b"examples"} if examples_present else {}
    # Expiry is inclusive: the expires day still trains, the day after does not.
    families = (
        _experiment("expired", datetime.date(2026, 10, 19)),
        _experiment("last_day", datetime.date(2026, 10, 20)),
    )

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        metadata = experiments.run_experiments(context, _ModelStoreS3(objects), "bucket", PARTITION, families)

    assert trained == (["last_day"] if examples_present else [])
    assert metadata["expired_skipped"].value == "expired on 2026-10-19"
    assert ("skipped" in metadata) is not examples_present


def test_an_experiment_must_name_a_registered_serving_baseline_and_an_expiry():
    with pytest.raises(ValueError, match="needs a baseline and an expires day"):
        ModelFamily(name="open_ended", feature_set=REPORT_EMBEDDINGS_FEATURE_SET, experiment=True)
    serving = ModelFamily(name=NN_MODEL_NAME, feature_set=REPORT_EMBEDDINGS_FEATURE_SET)
    chained = ModelFamily(
        name="chained",
        feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
        experiment=True,
        baseline="first",
        expires=datetime.date(2026, 12, 31),
    )
    assert family_problems((serving, _experiment("first", datetime.date(2026, 12, 31)), chained)) == [
        "experiment chained names baseline first, which is not a serving family"
    ]


def _sources(known_at: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "report_id": [f"r{index}" for index in range(len(known_at))],
            "known_at": pd.to_datetime(known_at, utc=True),
        }
    )


@pytest.fixture
def registered(monkeypatch):
    frames: dict[str, pd.DataFrame | None] = {}
    monkeypatch.setattr(side_inputs, "SIDE_INPUT_LOADERS", {})
    side_inputs.register_side_input(
        SideInputLoader(
            key=SIDE_INPUT, as_of_column="known_at", load=lambda client, bucket, prefix, day: frames.get(day)
        )
    )
    return frames


def test_a_side_input_is_cut_at_the_partition_end_and_read_only_as_of_a_moment(registered):
    registered[PARTITION] = _sources(["2026-10-19T12:00:00", "2026-10-21T00:00:00", "2026-10-21T00:00:01"])

    extras = load_side_inputs(None, "bucket", PREFIX, PARTITION, [SIDE_INPUT])

    # A row known after the partition end did not exist on dt=D.
    assert list(extras[SIDE_INPUT]["report_id"]) == ["r0", "r1"]
    # A moment on dt=D-1 sees only what was known by then, as the report vector rule does.
    moment = datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC)
    assert list(rows_as_of(extras, SIDE_INPUT, moment)["report_id"]) == ["r0"]
    with pytest.raises(SideInputError, match="only as of a moment"):
        rows_as_of(extras, SIDE_INPUT, None)


def test_a_missing_side_input_object_leaves_its_key_out(registered):
    assert load_side_inputs(None, "bucket", PREFIX, PARTITION, [SIDE_INPUT]) == {}


@pytest.mark.parametrize(
    "frame,message",
    [
        (pd.DataFrame({"report_id": ["r0"]}), "has no known_at column"),
        (
            pd.DataFrame({"report_id": ["r0"], "known_at": pd.to_datetime([None], utc=True)}),
            "rows with no known_at",
        ),
        (
            pd.DataFrame({"report_id": ["r0"], "known_at": pd.to_datetime(["2026-10-19"])}),
            "not a timezone-aware timestamp",
        ),
    ],
    ids=["no_column", "null_moment", "naive_moment"],
)
def test_a_side_input_without_a_usable_as_of_column_is_refused(registered, frame, message):
    registered[PARTITION] = frame

    with pytest.raises(SideInputError, match=message):
        load_side_inputs(None, "bucket", PREFIX, PARTITION, [SIDE_INPUT])


def test_a_side_input_without_a_registered_loader_is_refused(registered):
    with pytest.raises(SideInputError, match="no registered loader"):
        load_side_inputs(None, "bucket", PREFIX, PARTITION, ["unregistered"])


def test_vs_baseline_pairs_each_seed_inside_each_team_on_the_same_holdout_rows():
    # Team 1 ranks its own reports perfectly under the experiment's first seed, while the pooled
    # order mixes the teams. The third head has only negatives on the holdout, so nothing pairs.
    labels = np.array([[1, 1, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    table = ExampleTable(
        rows=pd.DataFrame({"report_id": ["a", "b", "c", "d"], "report_team_id": [1, 1, 2, 2]}),
        labels=labels,
        holdout=np.ones_like(labels, dtype=bool),
    )
    perfect = labels.copy()
    inverted = 1 - labels

    block = vs_baseline_block(
        table,
        baseline=NN_MODEL_NAME,
        seeds=(0, 1),
        experiment_scores=[perfect, inverted],
        baseline_scores=[inverted, inverted],
    )

    first, _, third = NN_HEAD_NAMES
    paired = {
        "experiment_aucs": [1.0, 0.0],
        "baseline_aucs": [0.0, 0.0],
        "paired_seeds": 2,
        "mean_delta_auc": 0.5,
        "min_delta_auc": 0.0,
        "max_delta_auc": 1.0,
        "wins": 1,
    }
    assert block["heads"][first]["within_team"] == paired
    assert block["heads"][first]["pooled"] == paired
    assert block["heads"][third]["within_team"]["paired_seeds"] == 0
    assert block["heads"][third]["within_team"]["mean_delta_auc"] is None


def _signal_log(signals: list[tuple[str, str, str, str]]) -> bytes:
    table = pa.Table.from_pylist(
        [
            {
                "signal_id": signal_id,
                "team_id": 1,
                "report_id": report_id,
                "source_product": product,
                "embedding_inserted_at": datetime.datetime.fromisoformat(inserted_at),
                "is_deleted": False,
            }
            for signal_id, report_id, product, inserted_at in signals
        ],
        schema=SIGNAL_EMBEDDINGS_SCHEMA,
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def test_a_late_signal_does_not_leak_into_an_earlier_row():
    day_before, day = datetime.date(2026, 10, 19), datetime.date(2026, 10, 20)
    objects = {
        partition_object_key(PREFIX, SIGNAL_EMBEDDINGS_TABLE, day_before.isoformat()): _signal_log(
            [("s1", "r1", "error_tracking", "2026-10-19T10:00:00+00:00")]
        ),
        partition_object_key(PREFIX, SIGNAL_EMBEDDINGS_TABLE, day.isoformat()): _signal_log(
            [("s2", "r1", "github", "2026-10-20T10:00:00+00:00")]
        ),
    }
    vectors = pd.DataFrame(
        {
            "embedding_small": [np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)] * 2,
            "embedding_inserted_at": pd.to_datetime(["2026-10-19T00:00:00"] * 2, utc=True),
        },
        index=pd.Index(["r1", "r2"], name="report_id"),
    )
    extras = {
        REPORT_EMBEDDINGS_EXTRA: vectors,
        **load_side_inputs(_ModelStoreS3(objects), "bucket", PREFIX, PARTITION, [REPORT_SOURCES_EXTRA]),
    }
    rows = pd.DataFrame(
        {"snapshot_date": [day_before, day, day_before], "report_id": ["r1", "r1", "r2"], "priority": [None] * 3}
    )

    matrix = pd.DataFrame(
        report_matrix(rows, extras, REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET),
        columns=list(REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET.feature_names),
    )

    columns = ["source_error_tracking", "source_github", "source_other", "source_count", "has_sources"]
    # The github signal landed on dt=D, after the dt=D-1 row's moment, so only the dt=D row sees it.
    # A report with no signals has zero in every source column.
    assert matrix[columns].values.tolist() == [[1, 0, 0, 1, 1], [1, 1, 0, 2, 1], [0, 0, 0, 0, 0]]
