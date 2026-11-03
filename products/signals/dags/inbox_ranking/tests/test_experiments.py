import json
import datetime
import dataclasses

import pytest

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.parquet as pq

from posthog import settings

from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    PROJECT_VECTOR_KINDS,
    REPORT_EMBEDDINGS_EXTRA,
    REPORT_EMBEDDINGS_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
    REPORT_SOURCES_EXTRA,
)
from products.signals.backend.ranking.model_store import ONNX_OUTPUT_HEADS_KEY
from products.signals.backend.ranking.serving_manifest import ONNX_MODEL_FILE, ONNX_MODEL_KIND
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import (
    EMBEDDINGS_TABLE,
    LABELS_TABLE,
    SIGNAL_EMBEDDINGS_SCHEMA,
    SIGNAL_EMBEDDINGS_TABLE,
    USER_INTERACTIONS_SCHEMA,
    USER_INTERACTIONS_TABLE,
)
from products.signals.dags.inbox_ranking.multihead.inputs import NetworkConfig
from products.signals.dags.inbox_ranking.multihead.local import report_vectors
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable, project_context, report_matrix
from products.signals.dags.inbox_ranking.nn import experiments, pair_lane
from products.signals.dags.inbox_ranking.nn.dag import NN_EXAMPLES_TABLE
from products.signals.dags.inbox_ranking.nn.examples import NN_HEAD_NAMES, NN_HEADS, build_examples, examples_arrow
from products.signals.dags.inbox_ranking.nn.model import network_recipe, onnx_probabilities, vs_baseline_block
from products.signals.dags.inbox_ranking.nn.pair_grade import DOGFOOD_TEAM_ID, pair_vs_baseline_block
from products.signals.dags.inbox_ranking.nn.pair_lane import (
    PAIR_SETTINGS,
    broadcast_report_scores,
    report_positions,
    train_pair_candidate,
)
from products.signals.dags.inbox_ranking.nn.pairs import NN_PAIR_EXAMPLES_TABLE, PAIR_EXAMPLES_SCHEMA
from products.signals.dags.inbox_ranking.tests.test_multihead import (
    D0,
    DAYS,
    HOLDOUT_DAYS,
    TEAMS,
    _birth,
    _SyntheticInbox,
)
from products.signals.dags.inbox_ranking.tests.test_nn import _S3, _parquet
from products.signals.dags.inbox_ranking.tests.test_training import _ModelStoreS3
from products.signals.dags.inbox_ranking.training import side_inputs
from products.signals.dags.inbox_ranking.training.dag import METADATA_FILE, model_object_key
from products.signals.dags.inbox_ranking.training.families import (
    MODEL_FAMILIES,
    NN_MODEL_NAME,
    NN_PAIR_BASE_MODEL_NAME,
    NN_PAIR_USER_MODEL_NAME,
    NN_WITH_PRIO_FAMILY,
    NN_WITH_PRIO_MODEL_NAME,
    PAIR_GRAIN,
    ModelFamily,
    family_problems,
    serving_families,
)
from products.signals.dags.inbox_ranking.training.recipe import model_recipe
from products.signals.dags.inbox_ranking.training.side_inputs import (
    SideInputError,
    SideInputLoader,
    load_side_inputs,
    rows_as_of,
)
from products.signals.dags.inbox_ranking.training.telemetry import experiment_comparison_events

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


def _pair_experiment(
    name: str,
    *,
    baseline: str | None = None,
    reference: str | None = NN_WITH_PRIO_MODEL_NAME,
    expires: datetime.date = datetime.date(2026, 12, 31),
    heads: tuple[str, ...] = ("open", "action"),
    experiment: bool = True,
) -> ModelFamily:
    return ModelFamily(
        name=name,
        feature_set=NN_WITH_PRIO_FAMILY.feature_set,
        learner=ONNX_MODEL_KIND,
        location=NN_WITH_PRIO_FAMILY.location,
        experiment=experiment,
        baseline=baseline,
        expires=expires,
        grain=PAIR_GRAIN,
        heads=heads,
        reference=reference,
    )


@pytest.mark.parametrize("examples_present", [True, False])
def test_an_expired_experiment_and_a_day_without_examples_train_nothing(monkeypatch, examples_present):
    trained: list[str] = []

    def train_candidate(context, client, bucket, partition_key, family):
        trained.append(family.name)
        return {"heads_trained": dagster.MetadataValue.int(3)}

    def train_pair_candidate(context, client, bucket, partition_key, family):
        trained.append(f"{family.name} in the pair lane")
        return {"heads_trained": dagster.MetadataValue.int(2)}

    monkeypatch.setattr(experiments, "train_candidate", train_candidate)
    monkeypatch.setattr(experiments, "train_pair_candidate", train_pair_candidate)
    objects = {partition_object_key(PREFIX, NN_EXAMPLES_TABLE, PARTITION): b"examples"} if examples_present else {}
    # Expiry is inclusive: the expires day still trains, the day after does not.
    families = (
        _experiment("expired", datetime.date(2026, 10, 19)),
        _experiment("last_day", datetime.date(2026, 10, 20)),
        _pair_experiment("pair", expires=datetime.date(2026, 10, 20)),
    )

    with dagster.build_asset_context(partition_key=PARTITION) as context:
        metadata = experiments.run_experiments(context, _ModelStoreS3(objects), "bucket", PARTITION, families)

    assert trained == (["last_day", "pair in the pair lane"] if examples_present else [])
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


@pytest.mark.parametrize(
    "build",
    [
        lambda: ModelFamily(
            name="served_fixed",
            feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
            project_vector_kinds=(*PROJECT_VECTOR_KINDS, "fixed"),
        ),
        lambda: dataclasses.replace(_pair_experiment("pair_fixed"), project_vector_kinds=("typical", "fixed")),
        lambda: dataclasses.replace(
            _experiment("unknown_kind", datetime.date(2026, 12, 31)), project_vector_kinds=("typical", "seen")
        ),
    ],
    ids=["serving_family", "pair_experiment", "unknown_kind"],
)
def test_only_a_report_experiment_can_read_other_project_vector_kinds(build):
    with pytest.raises(ValueError, match="project vector kinds"):
        build()


@pytest.mark.parametrize(
    "families,selection",
    [
        ((_experiment("report", datetime.date(2026, 10, 20)),), [experiments.NN_EXPERIMENTS_ASSET]),
        (
            (
                _experiment("expired", datetime.date(2026, 10, 19)),
                _pair_experiment("pair", expires=datetime.date(2026, 10, 20)),
            ),
            [NN_PAIR_EXAMPLES_TABLE, experiments.NN_PAIR_EXPERIMENTS_ASSET],
        ),
        ((_pair_experiment("expired_pair", expires=datetime.date(2026, 10, 19)),), []),
    ],
    ids=["report_only", "pair_only", "nothing_live"],
)
def test_a_run_builds_pair_examples_only_for_a_live_pair_experiment_and_trains_it_after_them(families, selection):
    assert experiments.experiment_selection(families, datetime.date(2026, 10, 20)) == selection
    pair_examples = dagster.AssetKey(NN_PAIR_EXAMPLES_TABLE)
    # The report experiments stay apart from the pair examples, so a failed pair step cannot skip them.
    assert pair_examples in experiments.inbox_ranking_nn_pair_experiment_candidates.dependency_keys
    assert pair_examples not in experiments.inbox_ranking_nn_experiment_candidates.dependency_keys


@pytest.mark.parametrize(
    "build,message",
    [
        (lambda: _pair_experiment("served", experiment=False), "must be an experiment"),
        (lambda: _pair_experiment("unanchored", reference=None), "needs a baseline, a reference, or both"),
        (lambda: _pair_experiment("fixed_head", heads=("open", "fixed")), "declares heads"),
    ],
    ids=["pair_serving_family", "no_baseline_or_reference", "fixed_is_not_a_pair_head"],
)
def test_a_pair_family_is_an_experiment_with_pair_heads_and_something_to_grade_against(build, message):
    with pytest.raises(ValueError, match=message):
        build()


_PRIO_SERVING = ModelFamily(name=NN_WITH_PRIO_MODEL_NAME, feature_set=NN_WITH_PRIO_FAMILY.feature_set)


@pytest.mark.parametrize(
    "families,problems",
    [
        ((_PRIO_SERVING, _pair_experiment("pair_base"), _pair_experiment("pair_user", baseline="pair_base")), []),
        (
            (_PRIO_SERVING, _pair_experiment("pair_user", baseline=NN_WITH_PRIO_MODEL_NAME)),
            ["experiment pair_user is pair grain and its baseline nn_with_prio_v2 is report grain"],
        ),
        (
            (_PRIO_SERVING, _pair_experiment("pair_user", baseline="pair_base")),
            ["experiment pair_user names baseline pair_base, which is not a registered pair experiment"],
        ),
        (
            (
                _PRIO_SERVING,
                _pair_experiment("pair_a", baseline="pair_b"),
                _pair_experiment("pair_b", baseline="pair_a"),
            ),
            [
                "experiment pair_a has a baseline cycle: pair_a -> pair_b -> pair_a",
                "experiment pair_b has a baseline cycle: pair_b -> pair_a -> pair_b",
            ],
        ),
        (
            (_PRIO_SERVING, _pair_experiment("pair_base", reference="pair_base")),
            ["experiment pair_base names reference pair_base, which is not a report-grain serving family"],
        ),
    ],
    ids=["valid_pair_chain", "mixed_grain_baseline", "unregistered_pair_baseline", "baseline_cycle", "pair_reference"],
)
def test_a_pair_experiment_names_a_registered_pair_baseline_and_a_report_serving_reference(families, problems):
    assert family_problems(families) == problems
    assert all(family.name == NN_WITH_PRIO_MODEL_NAME for family in serving_families(families))


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
    # A report-grain experiment's events keep the fields they had before pair grain existed.
    [event, *_] = experiment_comparison_events({"model_name": "experiment", "vs_baseline": block})
    assert set(event.properties) == {
        "model_name",
        "model_version",
        "run_id",
        "recipe_hash",
        "baseline_model_name",
        "seeds",
        "head",
        "train_rows",
        "holdout_rows",
        "holdout_positives",
        *(
            f"{read}_{key}"
            for read in ("within_team", "pooled")
            for key in ("paired_seeds", "mean_delta_auc", "min_delta_auc", "max_delta_auc", "wins")
        ),
    }
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

    # The dogfood team ranks backwards, so only the read without it sees the customer team's order.
    dogfood = (table.rows["report_team_id"].to_numpy() == DOGFOOD_TEAM_ID)[:, None]
    mixed = vs_baseline_block(
        table,
        baseline=NN_MODEL_NAME,
        seeds=(0,),
        experiment_scores=[np.where(dogfood, inverted, perfect)],
        baseline_scores=[inverted],
    )
    assert mixed["heads"][first]["within_team"]["experiment_aucs"] == [0.5]
    assert mixed["heads"][first]["within_team_non_dogfood"]["experiment_aucs"] == [1.0]


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


def test_a_report_family_recipe_has_no_pair_keys_so_its_hash_stays_as_it_was():
    config = NetworkConfig()
    assert network_recipe(NN_WITH_PRIO_FAMILY, config, ("open",)) == model_recipe(
        model_kind=ONNX_MODEL_KIND,
        feature_set=NN_WITH_PRIO_FAMILY.feature_set,
        heads=NN_HEADS,
        learner_params=dataclasses.asdict(config),
        project_vector_kinds=("open",),
    )
    pair_recipe = network_recipe(_pair_experiment("pair"), config, ("open",), PAIR_SETTINGS)
    assert (pair_recipe["grain"], pair_recipe["pair"], list(pair_recipe["heads"])) == (
        PAIR_GRAIN,
        PAIR_SETTINGS,
        ["open", "action"],
    )


def test_a_reference_score_is_broadcast_to_every_pair_of_its_report():
    day = datetime.date(2026, 10, 1)
    reports = pd.DataFrame({"report_id": ["a", "b", "c"], "snapshot_date": [day] * 3, "report_team_id": [3, 3, 4]})
    pairs = pd.DataFrame({"report_id": ["b", "a", "b", "z"], "snapshot_date": [day] * 4})
    # One column per report-grain head, in NN_HEAD_NAMES order: open, action, fixed.
    report_scores = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]], dtype=np.float32)

    scores = broadcast_report_scores(report_scores, report_positions(reports, pairs), NN_HEAD_NAMES, ("action", "open"))

    np.testing.assert_allclose(scores[:3], [[0.5, 0.4], [0.2, 0.1], [0.5, 0.4]])
    # A pair whose report has no row gets no score rather than another report's.
    assert np.isnan(scores[3]).all()


def _pair_frame(users: list[tuple[int, str, int, bool, list[int]]]) -> pd.DataFrame:
    """One pair per (user, label), each user's reports invented in order."""
    rows = []
    for team_id, user, prior_views, suggested, labels in users:
        for position, label in enumerate(labels):
            rows.append(
                {
                    "report_id": f"{user}-{position}",
                    "report_team_id": team_id,
                    "user_distinct_id": user,
                    "prior_views": prior_views,
                    "is_suggested_reviewer": suggested,
                    "label": label,
                }
            )
    return pd.DataFrame(rows)


def test_the_pair_grade_is_within_user_with_dogfood_history_and_reviewer_slices_and_a_team_interval():
    frame = _pair_frame(
        [
            (3, "u1", 12, True, [1, 0]),
            (4, "u3", 20, False, [1, 0, 0]),
            (DOGFOOD_TEAM_ID, "u4", 15, False, [1, 0]),
            # One outcome class only: the user has no within-user pair and is left out.
            (3, "u2", 0, False, [0, 0]),
        ]
    )
    labels = frame[["label"]].to_numpy(dtype=np.float32)
    table = ExampleTable(rows=frame, labels=labels, holdout=np.ones_like(labels, dtype=bool))
    perfect = labels.copy()
    # Right inside u3 (two pairs), wrong inside u1 and u4 (one pair each): macro 1/3, pooled 2/4.
    baseline = np.array([[0], [1], [1], [0], [0], [0], [1], [0], [0]], dtype=np.float32)
    # A report-level score that ties inside every user.
    reference = np.full_like(labels, 0.5)

    block = pair_vs_baseline_block(
        table,
        ("open",),
        baseline="pair_base",
        reference=NN_WITH_PRIO_MODEL_NAME,
        seeds=(0, 1),
        experiment_scores=[perfect, perfect],
        baseline_scores=[baseline, baseline],
        reference_scores=[reference, reference],
    )

    scopes = block["heads"]["open"]["scopes"]
    every = scopes["all"]["all"]
    assert (every["users"], every["teams"]) == (3, 3)
    assert every["baseline"]["macro"] == pytest.approx([1 / 3, 1 / 3])
    assert every["baseline"]["pooled"] == pytest.approx([0.5, 0.5])
    assert every["vs_baseline"]["macro"]["mean_delta_auc"] == pytest.approx(2 / 3)
    assert every["vs_baseline"]["pooled"]["mean_delta_auc"] == pytest.approx(0.5)
    assert every["vs_reference"]["macro"]["mean_delta_auc"] == pytest.approx(0.5)
    interval = every["vs_baseline"]["macro_team_interval"]
    assert interval["teams"] == 3
    assert 0 <= interval["low"] <= 2 / 3 <= interval["high"] <= 1
    # Leaving the dogfood project's user out leaves u1 (wrong) and u3 (right) in the 10+ bucket.
    with_history = scopes["non_dogfood"]["history_10_plus"]
    assert (with_history["users"], with_history["baseline"]["macro"]) == (2, pytest.approx([0.5, 0.5]))
    assert scopes["all"]["history_0"]["users"] == 0
    assert scopes["all"]["history_0"]["vs_baseline"]["macro"]["paired_seeds"] == 0
    # One team cannot be resampled into an interval.
    assert scopes["all"]["suggested_reviewer"]["vs_baseline"]["macro_team_interval"]["low"] is None

    events = experiment_comparison_events({"model_name": "pair_user", "vs_baseline": block})
    assert len(events) == len(scopes) * len(scopes["all"])
    [event] = [
        e for e in events if (e.properties["scope"], e.properties["slice"]) == ("non_dogfood", "history_10_plus")
    ]
    assert event.properties["grain"] == PAIR_GRAIN
    assert event.properties["reference_model_name"] == NN_WITH_PRIO_MODEL_NAME
    assert event.properties["vs_baseline_within_user_macro_mean_delta_auc"] == pytest.approx(0.5)
    assert event.properties["vs_reference_within_user_macro_mean_delta_auc"] == pytest.approx(0.5)


def _pair_examples(report_rows: pd.DataFrame, report_labels: np.ndarray, report_holdout: np.ndarray) -> pa.Table:
    """Two users per report with an `open` example: the first opens what the report's `open` label
    says and has history, the second never opens and has none."""
    open_index, action_index = NN_HEAD_NAMES.index("open"), NN_HEAD_NAMES.index("action")
    rows = []
    for position, report in report_rows.iterrows():
        if np.isnan(report_labels[position, open_index]):
            continue
        for user, prior_views in (("reader", 12), ("skimmer", 0)):
            opened = user == "reader" and bool(report_labels[position, open_index])
            rows.append(
                {
                    "snapshot_date": report["snapshot_date"],
                    "report_id": report["report_id"],
                    "report_team_id": int(report["report_team_id"]),
                    "user_distinct_id": f"{user}-{report['report_team_id']}",
                    "holdout": bool(report_holdout[position, open_index]),
                    "open_label": float(opened),
                    "action_label": float(opened and report_labels[position, action_index] == 1),
                    "user_open_reports": prior_views,
                    "user_dismiss_reports": 0,
                    "prior_views": prior_views,
                    "days_since_last_view": 1.0 if prior_views else 90.0,
                    "has_history": bool(prior_views),
                    "is_suggested_reviewer": user == "reader",
                    "suggested_reviewer_source": "reviewers",
                }
            )
    return pa.Table.from_pylist(rows, schema=PAIR_EXAMPLES_SCHEMA)


def _reader_history(inbox: _SyntheticInbox, day: str) -> pa.Table:
    """Each team's reader viewed every report of the team it opens, the day after its birth."""
    rows = [
        {
            "snapshot_date": datetime.date.fromisoformat(day),
            "report_id": report_id,
            "report_team_id": int(report["team"]),
            "user_distinct_id": f"reader-{report['team']}",
            "first_viewed_at": (_birth(int(report["born"])) + pd.Timedelta(days=1)).to_pydatetime(),
        }
        for report_id, report in inbox.reports.iterrows()
        if report["open"]
    ]
    return pa.Table.from_pylist(rows, schema=USER_INTERACTIONS_SCHEMA)


@pytest.mark.parametrize(
    "model_name,pairs_present",
    [(NN_PAIR_USER_MODEL_NAME, True), (NN_PAIR_BASE_MODEL_NAME, True), (NN_PAIR_USER_MODEL_NAME, False)],
    ids=["user_family", "base_family", "user_family_without_pairs"],
)
def test_a_registered_pair_family_trains_scores_and_is_graded_within_user(monkeypatch, model_name, pairs_present):
    pytest.importorskip("torch")
    monkeypatch.setattr("products.signals.dags.inbox_ranking.nn.dag.capture_training_events", lambda *a, **k: None)
    monkeypatch.setattr(
        pair_lane, "NETWORK_CONFIG", NetworkConfig(projection_dim=8, trunk_dim=8, dropout=0.1, epochs=40, batch_size=32)
    )
    monkeypatch.setattr(pair_lane, "EXPERIMENT_SEEDS", (0, 1))
    monkeypatch.setattr(pair_lane, "training_consent_team_ids", lambda: frozenset(TEAMS))
    monkeypatch.setattr(pair_lane, "team_organizations", lambda team_ids: {t: f"org-{t}" for t in team_ids})
    family = next(family for family in MODEL_FAMILIES if family.name == model_name)
    inbox = _SyntheticInbox()
    embeddings, labels = inbox.embeddings(), inbox.labels()
    examples = build_examples(inbox.snapshots(), report_vectors(embeddings), holdout_days=HOLDOUT_DAYS)
    table = examples.table
    day = (D0 + datetime.timedelta(days=DAYS - 1)).isoformat()
    pairs = _pair_examples(table.rows, table.labels, table.holdout)
    objects = {
        partition_object_key(PREFIX, NN_EXAMPLES_TABLE, day): _parquet(examples_arrow(examples)),
        partition_object_key(PREFIX, EMBEDDINGS_TABLE, day): _parquet(embeddings),
        partition_object_key(PREFIX, LABELS_TABLE, day): _parquet(labels),
        partition_object_key(PREFIX, USER_INTERACTIONS_TABLE, day): _parquet(_reader_history(inbox, day)),
    }
    if pairs_present:
        objects[partition_object_key(PREFIX, NN_PAIR_EXAMPLES_TABLE, day)] = _parquet(pairs)
    client = _S3(objects)

    with dagster.build_asset_context(partition_key=day) as context:
        result = train_pair_candidate(context, client, "bucket", day, family)

    metadata_key = model_object_key(PREFIX, family.name, day, METADATA_FILE)
    if not pairs_present:
        assert result["skipped"].value is True
        assert metadata_key not in client.objects
        return
    metadata = json.loads(client.objects[metadata_key])
    assert (metadata["grain"], metadata["recipe"]["grain"]) == (PAIR_GRAIN, PAIR_GRAIN)
    assert (metadata["feature_set"], metadata["user_vector_kinds"]) == (family.feature_set.name, ["open", "dismiss"])
    assert [head["head"] for head in metadata["heads"]] == ["open", "action"]
    block = metadata["vs_baseline"]
    assert (block["grain"], block["baseline"], block["reference"]) == (
        PAIR_GRAIN,
        family.baseline,
        NN_WITH_PRIO_MODEL_NAME,
    )
    for grade in block["heads"].values():
        every = grade["scopes"]["all"]["all"]
        assert every["vs_reference"]["macro"]["paired_seeds"] == 2
        if family.baseline is None:
            assert every["vs_baseline"] is None
        else:
            assert every["vs_baseline"]["macro"]["paired_seeds"] == 2
        # The skimmers never open, so only the readers have both classes; the dogfood readers drop out.
        assert grade["scopes"]["non_dogfood"]["all"]["users"] < every["users"]
    opened = block["heads"]["open"]["scopes"]["all"]["all"]
    assert min(opened["experiment"]["macro"]) > 0.65
    assert min(opened["reference"]["macro"]) > 0.75

    pair_table = pair_lane.pair_example_table(pairs.to_pandas(), table.rows, family.heads)
    history = pair_lane.load_user_history(client, "bucket", PREFIX, day)
    inputs = pair_lane.pair_network_inputs(
        pair_table,
        report_vectors(embeddings),
        family.feature_set,
        project_context(pair_table.rows, labels, embeddings),
        history,
        embeddings,
    )
    scores = onnx_probabilities(
        client.objects[model_object_key(PREFIX, family.name, day, ONNX_MODEL_FILE)],
        inputs,
        metadata[ONNX_OUTPUT_HEADS_KEY],
    )
    cold_start = (pair_table.rows["prior_views"] == 0).to_numpy()
    assert cold_start.any()
    assert all(np.isfinite(head_scores).all() for head_scores in scores.values())
