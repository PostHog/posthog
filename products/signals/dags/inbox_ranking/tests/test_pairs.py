import io
import datetime
from typing import Any

import pytest

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from posthog import settings

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS, PAIR_FEATURE_NAMES
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import (
    EMBEDDINGS_SCHEMA,
    EMBEDDINGS_TABLE,
    REVIEWERS_SCHEMA,
    USER_INTERACTIONS_SCHEMA,
    USER_INTERACTIONS_TABLE,
)
from products.signals.dags.inbox_ranking.dataset.project_vectors import USER_VECTOR_KINDS, VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import ProjectContext
from products.signals.dags.inbox_ranking.multihead.local import report_vectors
from products.signals.dags.inbox_ranking.nn import pair_lane
from products.signals.dags.inbox_ranking.nn.dag import NN_EXAMPLES_TABLE
from products.signals.dags.inbox_ranking.nn.pair_lane import load_user_history, pair_example_table, pair_network_inputs
from products.signals.dags.inbox_ranking.nn.pairs import (
    IMPRESSIONS_SOURCE,
    NN_PAIR_EXAMPLES_TABLE,
    PAIR_EXAMPLES_SCHEMA,
    REVIEWERS_SOURCE,
    build_pair_examples,
    pair_rows,
    pair_user_vectors,
)
from products.signals.dags.inbox_ranking.tests.test_nn import _S3, _parquet
from products.signals.dags.inbox_ranking.training.families import (
    MODEL_FAMILIES,
    NN_PAIR_BASE_MODEL_NAME,
    NN_PAIR_USER_MODEL_NAME,
)

PREFIX = settings.INBOX_RANKING_DATASET_S3_PREFIX
BIRTH = datetime.date(2026, 8, 1)
BIRTH_START = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
LABEL_DAY = BIRTH + datetime.timedelta(days=7)
ORGANIZATIONS = {2: "org-a", 9: "org-b"}
TARGET, PAST = "report-target", "report-past"
FAMILIES = {family.name: family for family in MODEL_FAMILIES}


def _at(days: float) -> datetime.datetime:
    return BIRTH_START + datetime.timedelta(days=days)


def _embeddings() -> pa.Table:
    # The target report is born and embedded on its birth day, after the start of that day.
    return pa.Table.from_pylist(
        [
            {
                "snapshot_date": LABEL_DAY,
                "report_id": report_id,
                "report_team_id": 2,
                "embedding_small": [value] * EMBEDDING_DIMENSIONS,
                "embedding_inserted_at": inserted_at,
                "embedding_rendering": "title_summary_v1",
                "is_tombstone": False,
            }
            for report_id, value, inserted_at in ((TARGET, 9.0, _at(0.4)), (PAST, 3.0, _at(-5)))
        ],
        schema=EMBEDDINGS_SCHEMA,
    )


def _interactions(rows: list[dict[str, Any]], team_id: int = 2) -> pa.Table:
    return pa.Table.from_pylist(
        [{"snapshot_date": LABEL_DAY, "report_team_id": team_id, **row} for row in rows],
        schema=USER_INTERACTIONS_SCHEMA,
    )


# u1 viewed the past report two days before the birth and the target report after it.
HISTORY_ROWS = [
    {"report_id": PAST, "user_distinct_id": "u1", "first_viewed_at": _at(-2)},
    {"report_id": TARGET, "user_distinct_id": "u1", "first_viewed_at": _at(0.5)},
]
IMPRESSION_ROWS = [
    {"report_id": TARGET, "user_distinct_id": "u1", "first_impressed_at": _at(0.5), "first_opened_at": _at(0.6)},
    # Acted only after the horizon ends.
    {
        "report_id": TARGET,
        "user_distinct_id": "u2",
        "first_impressed_at": _at(1),
        "impressed_as_suggested_reviewer_count": 1,
        "first_implement_clicked_at": _at(9),
    },
    # Opened without an impression, and impressed only after the horizon ends.
    {"report_id": TARGET, "user_distinct_id": "u3", "first_opened_at": _at(1)},
    {"report_id": TARGET, "user_distinct_id": "u4", "first_impressed_at": _at(8.1)},
    {"report_id": TARGET, "user_distinct_id": "u5", "first_impressed_at": _at(2), "first_create_pr_clicked_at": _at(3)},
]
REPORTS = pd.DataFrame({"report_id": [TARGET], "report_team_id": [2], "holdout": [True]})


def _pair_rows(reviewers: pa.Table | None) -> list[dict[str, Any]]:
    return pair_rows(
        REPORTS,
        _interactions(IMPRESSION_ROWS),
        _interactions(HISTORY_ROWS),
        _embeddings(),
        birth_day=BIRTH,
        reviewers=reviewers,
        organizations=ORGANIZATIONS,
    )


@parameterized.expand(
    [
        ("reviewers_snapshot", True, {"u1": False, "u2": False, "u5": True}, REVIEWERS_SOURCE),
        ("impressions_fallback", False, {"u1": False, "u2": True, "u5": False}, IMPRESSIONS_SOURCE),
    ]
)
def test_pairs_are_the_users_impressed_within_the_horizon_with_labels_inside_it(
    _name: str, with_reviewers: bool, suggested: dict[str, bool], source: str
) -> None:
    reviewers = (
        pa.Table.from_pylist([{"report_id": TARGET, "user_distinct_id": "u5"}], schema=REVIEWERS_SCHEMA)
        if with_reviewers
        else None
    )

    rows = {row["user_distinct_id"]: row for row in _pair_rows(reviewers)}

    assert {user: (row["open_label"], row["action_label"]) for user, row in rows.items()} == {
        "u1": (1.0, 0.0),
        "u2": (0.0, 0.0),
        "u5": (0.0, 1.0),
    }
    assert {user: row["is_suggested_reviewer"] for user, row in rows.items()} == suggested
    assert {row["suggested_reviewer_source"] for row in rows.values()} == {source}
    assert pa.Table.from_pylist(list(rows.values()), schema=PAIR_EXAMPLES_SCHEMA).num_rows == 3


def test_a_pair_user_vector_never_includes_the_examples_own_report() -> None:
    rows = _pair_rows(reviewers=None)
    pairs = pd.DataFrame(rows)

    vectors = pair_user_vectors(pairs, _interactions(HISTORY_ROWS), _embeddings(), organizations=ORGANIZATIONS)

    u1 = pairs.index[pairs["user_distinct_id"] == "u1"][0]
    open_kind = USER_VECTOR_KINDS.index("open")
    assert vectors[u1, open_kind] == pytest.approx([3.0] * EMBEDDING_DIMENSIONS)
    assert (rows[u1]["user_open_reports"], rows[u1]["prior_views"], rows[u1]["days_since_last_view"]) == (1, 1, 2.0)
    assert rows[u1]["has_history"]
    others = pairs.index[pairs["user_distinct_id"] != "u1"]
    assert not np.any(vectors[others])
    assert not any(rows[index]["has_history"] for index in others)


def test_a_partition_rerun_overwrites_only_its_own_object_and_drops_teams_without_consent() -> None:
    partition = LABEL_DAY.isoformat()
    earlier = partition_object_key(PREFIX, NN_PAIR_EXAMPLES_TABLE, (LABEL_DAY - datetime.timedelta(days=1)).isoformat())
    examples = pa.Table.from_pylist(
        [
            {"report_id": TARGET, "snapshot_date": BIRTH, "report_team_id": 2, "open_label": 1.0, "open_holdout": True},
            {
                "report_id": "report-other",
                "snapshot_date": BIRTH,
                "report_team_id": 9,
                "open_label": 0.0,
                "open_holdout": False,
            },
        ]
    )
    interactions = pa.concat_tables(
        [
            _interactions(HISTORY_ROWS + IMPRESSION_ROWS),
            _interactions([{"report_id": "report-other", "user_distinct_id": "u9", "first_impressed_at": _at(1)}], 9),
        ]
    )
    client = _S3(
        {
            partition_object_key(PREFIX, NN_EXAMPLES_TABLE, partition): _parquet(examples),
            partition_object_key(PREFIX, USER_INTERACTIONS_TABLE, partition): _parquet(interactions),
            partition_object_key(PREFIX, EMBEDDINGS_TABLE, partition): _parquet(_embeddings()),
            partition_object_key(PREFIX, NN_PAIR_EXAMPLES_TABLE, partition): b"previous run",
            earlier: b"earlier partition",
        }
    )
    before = dict(client.objects)

    with dagster.build_asset_context(partition_key=partition) as context:
        metadata = build_pair_examples(
            context, client, "bucket", partition, consent_team_ids=frozenset({2}), organizations=ORGANIZATIONS
        )

    written = partition_object_key(PREFIX, NN_PAIR_EXAMPLES_TABLE, partition)
    assert {key: body for key, body in client.objects.items() if key != written} == {
        key: body for key, body in before.items() if key != written
    }
    table = pq.read_table(io.BytesIO(client.objects[written]))
    assert table.schema == PAIR_EXAMPLES_SCHEMA
    assert set(table.column("user_distinct_id").to_pylist()) == {"u1", "u2", "u5"}
    assert metadata["excluded_no_training_consent_reports"].value == 1
    assert (metadata["rows"].value, metadata["history_0_rows"].value, metadata["history_1_9_rows"].value) == (3, 2, 1)


def _pair_embeddings() -> pa.Table:
    extra = [
        # (report, team, value): a report u2 dismissed, one u1 viewed in another organization, and one
        # u1 viewed in a team of its organization that has no training consent.
        ("report-dismissed", 2, 5.0),
        ("report-elsewhere", 9, 7.0),
        ("report-unconsented", 5, 11.0),
    ]
    rows = [
        {
            "snapshot_date": LABEL_DAY,
            "report_id": report_id,
            "report_team_id": team_id,
            "embedding_small": [value] * EMBEDDING_DIMENSIONS,
            "embedding_inserted_at": _at(-6),
            "embedding_rendering": "title_summary_v1",
            "is_tombstone": False,
        }
        for report_id, team_id, value in extra
    ]
    return pa.concat_tables([_embeddings(), pa.Table.from_pylist(rows, schema=EMBEDDINGS_SCHEMA)])


def test_each_pair_arm_builds_its_own_inputs_and_only_the_user_arm_reads_history(monkeypatch) -> None:
    monkeypatch.setattr(pair_lane, "training_consent_team_ids", lambda: frozenset({2, 9}))
    monkeypatch.setattr(
        pair_lane,
        "team_organizations",
        lambda team_ids: {t: o for t, o in {**ORGANIZATIONS, 5: "org-a"}.items() if t in team_ids},
    )
    partition = LABEL_DAY.isoformat()
    history_rows = pa.concat_tables(
        [
            _interactions(
                [
                    *HISTORY_ROWS,
                    {"report_id": "report-dismissed", "user_distinct_id": "u2", "first_ui_dismissed_at": _at(-1)},
                ]
            ),
            _interactions([{"report_id": "report-elsewhere", "user_distinct_id": "u1", "first_viewed_at": _at(-1)}], 9),
            _interactions(
                [{"report_id": "report-unconsented", "user_distinct_id": "u1", "first_viewed_at": _at(-1)}], 5
            ),
        ]
    )
    embeddings = _pair_embeddings()
    client = _S3({partition_object_key(PREFIX, USER_INTERACTIONS_TABLE, partition): _parquet(history_rows)})
    history = load_user_history(client, "bucket", PREFIX, partition)
    assert history is not None
    pairs = pd.DataFrame(
        pair_rows(
            REPORTS,
            _interactions(IMPRESSION_ROWS),
            history.interactions,
            embeddings,
            birth_day=BIRTH,
            reviewers=None,
            organizations=history.organizations,
        )
    )
    report_rows = pd.DataFrame(
        {"report_id": [TARGET], "snapshot_date": [BIRTH], "report_team_id": [2], "priority": ["P1"]}
    )
    table = pair_example_table(pairs, report_rows, ("open", "action"))
    # The team has an `open` history of all ones and too thin a `dismiss` history.
    project_vectors = np.zeros((1, len(VECTOR_KINDS), EMBEDDING_DIMENSIONS), dtype=np.float32)
    project_vectors[0, VECTOR_KINDS.index("open")] = 1.0
    project_has_history = np.zeros((1, len(VECTOR_KINDS)), dtype=np.float32)
    project_has_history[0, VECTOR_KINDS.index("open")] = 1.0
    project = ProjectContext(
        vectors=project_vectors, has_history=project_has_history, index=np.zeros(len(table.rows), dtype=np.int64)
    )
    arms = {
        name: pair_network_inputs(
            table, report_vectors(embeddings), FAMILIES[name].feature_set, project, history, embeddings
        )
        for name in (NN_PAIR_BASE_MODEL_NAME, NN_PAIR_USER_MODEL_NAME)
    }
    base, user = arms[NN_PAIR_BASE_MODEL_NAME], arms[NN_PAIR_USER_MODEL_NAME]

    assert base.reports.shape == user.reports.shape
    width = base.reports.shape[1] - len(PAIR_FEATURE_NAMES)
    np.testing.assert_array_equal(base.reports[:, :width], user.reports[:, :width])
    reviewer = width + PAIR_FEATURE_NAMES.index("is_suggested_reviewer")
    np.testing.assert_array_equal(base.reports[:, reviewer], user.reports[:, reviewer])
    row = {name: int(table.rows.index[table.rows["user_distinct_id"] == name][0]) for name in ("u1", "u2", "u5")}
    assert base.reports[row["u2"], reviewer] == 1.0
    assert not base.reports[:, width:reviewer].any()
    assert base.users is not None and not base.users.vectors[base.users.index].any()
    np.testing.assert_allclose(user.reports[row["u1"], width:reviewer], [np.log1p(1), 0.0, 2 / 90, 1.0])

    assert user.users is not None
    offsets = user.users.vectors[user.users.index]
    open_kind, dismiss_kind = USER_VECTOR_KINDS.index("open"), USER_VECTOR_KINDS.index("dismiss")
    # u1's open vector is the one past report it viewed before the birth day in this organization's
    # consented teams: the target report, the other organization's and the unconsented team's stay out.
    np.testing.assert_allclose(offsets[row["u1"], open_kind], 3.0 - 1.0)
    # u2 viewed nothing, and the team's dismiss history is too thin to offset its dismissals from.
    assert not offsets[row["u1"], dismiss_kind].any()
    assert not offsets[row["u2"]].any()
    assert not offsets[row["u5"]].any()
    # Without history the user reads as the longest time since a view, and nothing else.
    np.testing.assert_allclose(user.reports[row["u5"], width:reviewer], [0.0, 0.0, 1.0, 0.0])
