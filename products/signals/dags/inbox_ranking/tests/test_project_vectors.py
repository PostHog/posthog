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

from products.signals.backend.ranking import model_store
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS, PROJECT_VECTOR_KINDS
from products.signals.backend.ranking.serving_manifest import (
    PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    serving_engagement_key,
    serving_project_vectors_key,
    serving_user_vectors_key,
)
from products.signals.dags.inbox_ranking import common
from products.signals.dags.inbox_ranking.dataset import dag
from products.signals.dags.inbox_ranking.dataset.dag import EMBEDDINGS_SCHEMA, LABELS_SCHEMA, USER_INTERACTIONS_SCHEMA
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    CONTEXT_KINDS,
    ENGAGEMENT_EXPORT_COLUMNS,
    HISTORY_LIMIT,
    LABEL_COLUMNS,
    MIN_HISTORY_REPORTS,
    PROJECT_VECTORS_SCHEMA,
    PROJECT_VECTORS_SCHEMA_VERSION,
    USER_HISTORY_LIMIT,
    USER_VECTOR_KINDS,
    USER_VECTORS_DAY_SCHEMA,
    USER_VECTORS_SCHEMA,
    USER_VECTORS_SCHEMA_VERSION,
    project_vectors,
    user_vectors,
    with_user_hashes,
)
from products.signals.dags.inbox_ranking.mirror import dag as mirror_dag
from products.signals.dags.inbox_ranking.multihead.prototype import project_context
from products.signals.dags.inbox_ranking.nn.pairs import pair_user_vectors
from products.signals.dags.inbox_ranking.training import (
    dag as training_dag,
    telemetry,
)

AS_OF = datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)
BEFORE = AS_OF - datetime.timedelta(days=3)
AFTER = AS_OF + datetime.timedelta(hours=1)


def _report_id(team_id: int, index: int) -> str:
    return f"report-{team_id}-{index}"


def _embeddings(reports: list[tuple[int, int, float, datetime.datetime]]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "snapshot_date": AS_OF.date(),
                "report_id": _report_id(team_id, index),
                "report_team_id": team_id,
                "embedding_small": [value] * EMBEDDING_DIMENSIONS,
                "embedding_inserted_at": inserted_at,
                "embedding_rendering": "title_summary_v1",
                "is_tombstone": False,
            }
            for team_id, index, value, inserted_at in reports
        ],
        schema=EMBEDDINGS_SCHEMA,
    )


def _labels(engagements: list[tuple[int, int, str, datetime.datetime]]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"snapshot_date": AS_OF.date(), "report_id": _report_id(team_id, index), column: moment}
            for team_id, index, column, moment in engagements
        ],
        schema=LABELS_SCHEMA,
    )


def _rows_by_key(table: pa.Table) -> dict[tuple[int, str], dict[str, Any]]:
    return {(row["team_id"], row["kind"]): row for row in table.to_pylist()}


@parameterized.expand(
    [
        ("open", "first_opened_at"),
        ("action", "first_implement_clicked_at"),
        ("action", "first_reviewer_removed_at"),
        ("dismiss", "first_ui_dismissed_at"),
        ("fixed", "first_fixed_at"),
    ]
)
def test_only_engagement_and_vectors_before_as_of_enter_a_vector(kind: str, column: str) -> None:
    reports = [(2, index, 1.0, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    reports += [(2, 100, 9.0, BEFORE), (2, 101, 9.0, AFTER)]
    engagements = [(2, index, column, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    # Engaged after as_of, and engaged in time with a vector re-embedded after as_of.
    engagements += [(2, 100, column, AFTER), (2, 101, column, BEFORE)]

    rows = _rows_by_key(project_vectors(_labels(engagements), _embeddings(reports), AS_OF, CONTEXT_KINDS))

    assert rows[(2, kind)]["n_reports"] == MIN_HISTORY_REPORTS
    assert rows[(2, kind)]["vector"] == pytest.approx([1.0] * EMBEDDING_DIMENSIONS)
    assert rows[(2, "typical")]["n_reports"] == MIN_HISTORY_REPORTS + 1


def test_vectors_never_mix_teams_and_keep_the_latest_history() -> None:
    history = HISTORY_LIMIT + 3
    reports = [(2, index, float(index < 3), BEFORE) for index in range(history)]
    reports += [(7, index, 5.0, BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    # Team 2's three oldest opens hold the 1.0 vectors, so the latest HISTORY_LIMIT opens average to 0.
    engagements = [
        (2, index, "first_opened_at", BEFORE + datetime.timedelta(minutes=index)) for index in range(history)
    ]
    engagements += [(7, index, "first_opened_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]

    table = project_vectors(_labels(engagements), _embeddings(reports), AS_OF)
    rows = _rows_by_key(table)

    assert table.schema == PROJECT_VECTORS_SCHEMA
    assert rows[(2, "open")]["n_reports"] == HISTORY_LIMIT
    assert rows[(2, "open")]["vector"] == pytest.approx([0.0] * EMBEDDING_DIMENSIONS)
    assert rows[(2, "typical")]["vector"] == pytest.approx([3 / history] * EMBEDDING_DIMENSIONS)
    assert rows[(7, "open")]["vector"] == pytest.approx([5.0] * EMBEDDING_DIMENSIONS)
    assert rows[(7, "typical")]["vector"] == pytest.approx([5.0] * EMBEDDING_DIMENSIONS)


def test_a_team_below_the_history_threshold_keeps_a_zero_vector_row() -> None:
    thin = MIN_HISTORY_REPORTS - 1
    reports = [(2, index, 1.0, BEFORE) for index in range(thin)]
    engagements = [(2, index, "first_create_pr_clicked_at", BEFORE) for index in range(thin)]
    engagements += [(2, index, "first_fixed_at", BEFORE) for index in range(thin)]

    rows = _rows_by_key(project_vectors(_labels(engagements), _embeddings(reports), AS_OF))

    assert {kind: row["n_reports"] for (_, kind), row in rows.items()} == {
        "typical": thin,
        "open": 0,
        "action": thin,
        "dismiss": 0,
    }
    for row in rows.values():
        assert row["vector"] == [0.0] * EMBEDDING_DIMENSIONS


ORGANIZATIONS = {2: "org-a", 3: "org-a", 7: "org-b"}


def _interactions(views: list[tuple[int, int, str, str, datetime.datetime]]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "snapshot_date": AS_OF.date(),
                "report_id": _report_id(team_id, index),
                "report_team_id": team_id,
                "user_distinct_id": user,
                column: moment,
            }
            for team_id, index, user, column, moment in views
        ],
        schema=USER_INTERACTIONS_SCHEMA,
    )


def _user_rows(table: pa.Table) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(row["organization_id"], row["user_distinct_id"], row["kind"]): row for row in table.to_pylist()}


@parameterized.expand(
    [
        ("view_at_as_of", (2, 1, 9.0, BEFORE), (2, 1, "u1", "first_viewed_at", AS_OF)),
        ("dismiss_at_as_of", (2, 1, 9.0, BEFORE), (2, 1, "u1", "first_ui_dismissed_at", AS_OF)),
        ("embedding_after_as_of", (2, 1, 9.0, AFTER), (2, 1, "u1", "first_viewed_at", BEFORE)),
        ("other_organization", (7, 1, 9.0, BEFORE), (7, 1, "u1", "first_viewed_at", BEFORE)),
    ]
)
def test_user_vectors_take_only_history_known_at_as_of_from_the_same_organization(
    _name: str, report: tuple[int, int, float, datetime.datetime], view: tuple[int, int, str, str, datetime.datetime]
) -> None:
    # A view in another team of the same organization counts; the parameterized row must not.
    reports = [(2, 0, 1.0, BEFORE), (3, 0, 1.0, BEFORE), report]
    views = [(2, 0, "u1", "first_viewed_at", BEFORE), (3, 0, "u1", "first_viewed_at", BEFORE), view]

    table = user_vectors(_interactions(views), _embeddings(reports), AS_OF, organizations=ORGANIZATIONS)
    rows = _user_rows(table)

    assert table.schema == USER_VECTORS_SCHEMA
    assert rows[("org-a", "u1", "open")]["n_reports"] == 2
    assert rows[("org-a", "u1", "open")]["vector"] == pytest.approx([1.0] * EMBEDDING_DIMENSIONS)
    assert ("org-a", "u1", "dismiss") not in rows


def test_user_vectors_average_the_last_reports_and_skip_a_user_without_history() -> None:
    history = USER_HISTORY_LIMIT + 5
    reports = [(2, index, float(index), BEFORE) for index in range(history)]
    views = [
        (2, index, "u1", "first_viewed_at", BEFORE + datetime.timedelta(minutes=index)) for index in range(history)
    ]
    views.append((2, 0, "u2", "first_viewed_at", AFTER))

    rows = _user_rows(user_vectors(_interactions(views), _embeddings(reports), AS_OF, organizations=ORGANIZATIONS))

    newest = range(history - USER_HISTORY_LIMIT, history)
    assert set(rows) == {("org-a", "u1", "open")}
    assert rows[("org-a", "u1", "open")]["n_reports"] == USER_HISTORY_LIMIT
    assert rows[("org-a", "u1", "open")]["vector"] == pytest.approx([sum(newest) / len(newest)] * EMBEDDING_DIMENSIONS)
    assert rows[("org-a", "u1", "open")]["last_at"] == BEFORE + datetime.timedelta(minutes=history - 1)


def test_the_asset_writes_only_teams_opted_in_to_ai_training(monkeypatch) -> None:
    partition_key = (AS_OF.date() - datetime.timedelta(days=1)).isoformat()
    reports = [(team_id, index, 1.0, BEFORE) for team_id in (2, 7) for index in range(MIN_HISTORY_REPORTS)]
    # One fix lands at as_of, so it must stay out of the stored `fixed` vector.
    fixes = [(7, index, "first_fixed_at", BEFORE) for index in range(MIN_HISTORY_REPORTS - 1)]
    fixes.append((7, MIN_HISTORY_REPORTS - 1, "first_fixed_at", AS_OF))
    snapshots = {
        common.partition_object_key("inbox_ranking", dag.EMBEDDINGS_TABLE, partition_key): _embeddings(reports),
        common.partition_object_key("inbox_ranking", dag.LABELS_TABLE, partition_key): _labels(fixes),
    }
    captured: dict[str, Any] = {}

    def fake_write_parquet(client, bucket, key, table, snapshot_date=None, schema_version=None):
        captured.update(key=key, table=table, schema_version=schema_version)

    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "test-bucket")
    monkeypatch.setattr(dag, "s3_client", lambda: None)
    monkeypatch.setattr(dag, "read_parquet", lambda client, bucket, key, columns=None: snapshots[key].select(columns))
    monkeypatch.setattr(dag, "write_parquet", fake_write_parquet)
    monkeypatch.setattr(dag, "training_consent_team_ids", lambda: frozenset({7}))
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")

    dag.inbox_project_vectors(dagster.build_asset_context(partition_key=partition_key))

    assert captured["key"] == common.partition_object_key("inbox_ranking", dag.PROJECT_VECTORS_TABLE, partition_key)
    assert captured["schema_version"] == PROJECT_VECTORS_SCHEMA_VERSION
    assert set(captured["table"].column("team_id").to_pylist()) == {7}
    assert set(captured["table"].column("as_of").to_pylist()) == {AS_OF}
    rows = _rows_by_key(captured["table"])
    assert {kind for _, kind in rows} == set(CONTEXT_KINDS)
    assert rows[(7, "fixed")]["n_reports"] == MIN_HISTORY_REPORTS - 1


def _run_user_vectors_asset(monkeypatch, interactions: pa.Table, embeddings: pa.Table, consent: frozenset[int]):
    partition_key = (AS_OF.date() - datetime.timedelta(days=1)).isoformat()
    snapshots = {
        common.partition_object_key("inbox_ranking", dag.EMBEDDINGS_TABLE, partition_key): embeddings,
        common.partition_object_key("inbox_ranking", dag.USER_INTERACTIONS_TABLE, partition_key): interactions,
    }
    captured: dict[str, Any] = {}

    def fake_write_parquet(client, bucket, key, table, snapshot_date=None, schema_version=None):
        captured.update(key=key, table=table, schema_version=schema_version)

    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "test-bucket")
    monkeypatch.setattr(dag, "s3_client", lambda: None)
    monkeypatch.setattr(dag, "read_parquet", lambda client, bucket, key, columns=None: snapshots[key].select(columns))
    monkeypatch.setattr(dag, "write_parquet", fake_write_parquet)
    monkeypatch.setattr(dag, "training_consent_team_ids", lambda: consent)
    monkeypatch.setattr(
        dag, "team_organizations", lambda team_ids: {t: o for t, o in ORGANIZATIONS.items() if t in team_ids}
    )
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")
    dag.inbox_user_vectors(dagster.build_asset_context(partition_key=partition_key))
    assert captured["key"] == common.partition_object_key("inbox_ranking", dag.USER_VECTORS_TABLE, partition_key)
    assert captured["schema_version"] == USER_VECTORS_SCHEMA_VERSION
    return captured["table"]


def test_the_user_vectors_asset_matches_the_pair_lane_for_a_report_born_the_next_day(monkeypatch) -> None:
    reports = [(team_id, index, float(team_id + index), BEFORE) for team_id in (2, 3, 7) for index in range(3)]
    reports.append((2, 9, 50.0, AFTER))
    views = [
        (2, 0, "u1", "first_viewed_at", BEFORE),
        (3, 1, "u1", "first_viewed_at", BEFORE + datetime.timedelta(hours=1)),
        (2, 2, "u1", "first_ui_dismissed_at", BEFORE),
        (2, 1, "u1", "first_viewed_at", AFTER),
        (2, 9, "u1", "first_viewed_at", BEFORE),
        (3, 2, "u2", "first_viewed_at", BEFORE),
        (7, 0, "u1", "first_viewed_at", BEFORE),
        (7, 1, "u3", "first_viewed_at", BEFORE),
    ]
    interactions, embeddings = _interactions(views), _embeddings(reports)

    table = _run_user_vectors_asset(monkeypatch, interactions, embeddings, consent=frozenset({2, 3}))

    assert table.schema == USER_VECTORS_DAY_SCHEMA
    rows = _user_rows(table)
    # Team 7 has no training consent, so neither its user nor its organization gets a row.
    assert set(rows) == {("org-a", "u1", "open"), ("org-a", "u1", "dismiss"), ("org-a", "u2", "open")}
    assert rows[("org-a", "u1", "open")]["n_reports"] == 2
    pairs = pd.DataFrame(
        {
            "snapshot_date": [AS_OF.date()] * 3,
            "report_team_id": [2, 3, 2],
            "user_distinct_id": ["u1", "u1", "u2"],
        }
    )
    consented = {t: o for t, o in ORGANIZATIONS.items() if t in (2, 3)}
    rebuilt = pair_user_vectors(pairs, interactions, embeddings, organizations=consented)
    for position, user in enumerate(pairs["user_distinct_id"]):
        for kind_index, kind in enumerate(USER_VECTOR_KINDS):
            row = rows.get(("org-a", user, kind))
            expected = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32) if row is None else row["vector"]
            np.testing.assert_array_equal(rebuilt[position, kind_index], expected)


def _hashes(table: pa.Table) -> dict[tuple[str, str], str]:
    return {
        (row["organization_id"], row["user_distinct_id"]): row["user_hash"]
        for row in with_user_hashes(table).to_pylist()
    }


@parameterized.expand(
    [
        ("rows_reordered", lambda rows: list(reversed(rows)), False),
        ("last_at_moved", lambda rows: [{**rows[0], "last_at": AFTER}, *rows[1:]], False),
        ("count_changed", lambda rows: [{**rows[0], "n_reports": rows[0]["n_reports"] + 1}, *rows[1:]], True),
        (
            "vector_changed",
            lambda rows: [{**rows[0], "vector": [0.5] * EMBEDDING_DIMENSIONS}, *rows[1:]],
            True,
        ),
        ("kind_dropped", lambda rows: rows[1:], True),
    ]
)
def test_the_user_hash_changes_only_when_a_kind_count_or_vector_changes(_name: str, edit, changes: bool) -> None:
    reports = [(2, index, float(index), BEFORE) for index in range(3)]
    views = [
        (2, 0, "u1", "first_viewed_at", BEFORE),
        (2, 1, "u1", "first_ui_dismissed_at", BEFORE),
        (2, 2, "u2", "first_viewed_at", BEFORE),
    ]
    table = user_vectors(_interactions(views), _embeddings(reports), AS_OF, organizations=ORGANIZATIONS)
    rows = table.to_pylist()
    assert [(row["user_distinct_id"], row["kind"]) for row in rows[:2]] == [("u1", "dismiss"), ("u1", "open")]

    before = _hashes(table)
    after = _hashes(pa.Table.from_pylist(edit(rows), schema=USER_VECTORS_SCHEMA))

    assert len(set(before.values())) == 2
    assert (after[("org-a", "u1")] != before[("org-a", "u1")]) is changes
    assert after[("org-a", "u2")] == before[("org-a", "u2")]


def test_serving_reads_the_published_user_vectors_of_the_users_it_asks_for(monkeypatch: pytest.MonkeyPatch) -> None:
    reports = [(2, 0, 1.0, BEFORE), (7, 0, 2.0, BEFORE)]
    views = [(2, 0, "u1", "first_viewed_at", BEFORE), (7, 0, "u1", "first_viewed_at", BEFORE)]
    table = with_user_hashes(
        user_vectors(_interactions(views), _embeddings(reports), AS_OF, organizations=ORGANIZATIONS)
    )
    key = serving_user_vectors_key("inbox_ranking", (AS_OF.date() - datetime.timedelta(days=1)).isoformat())
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    monkeypatch.setattr(
        model_store.object_storage,
        "read_bytes",
        lambda name, bucket=None, *, missing_ok=False: buffer.getvalue() if name == key else None,
    )
    entry = ServingManifestEntry(
        key="nn@2026-07-29",
        model_name="nn",
        model_version="2026-07-29",
        model_kind="onnx",
        roles=[SERVED_ROLE],
        prefix="inbox_ranking/serving/models/nn@2026-07-29",
        heads=["open"],
        model_file="model.onnx",
    )
    manifest = ServingManifest(manifest_version=AS_OF.isoformat(), models=[entry], user_vectors=key)

    served = model_store.load_user_vectors(manifest, [("org-a", "u1"), ("org-a", "u9")])
    missing = model_store.load_user_vectors(manifest.model_copy(update={"user_vectors": None}), [("org-a", "u1")])

    assert served.available and not missing.available
    assert set(served.by_user) == {("org-a", "u1")}
    open_vector = served.by_user[("org-a", "u1")]["open"]
    assert open_vector.n_reports == 1
    assert open_vector.last_at == BEFORE
    np.testing.assert_array_equal(open_vector.vector, np.ones(EMBEDDING_DIMENSIONS, dtype=np.float32))
    assert served.hashes[("org-a", "u1")] == _hashes(table.drop_columns(["user_hash"]))[("org-a", "u1")]


def test_serving_reads_the_published_day_as_training_builds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    reports = [(2, index, float(index + 1), BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    reports += [(3, 0, 7.0, BEFORE)]
    engagements = [(2, index, "first_opened_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    engagements += [(2, index, "first_fixed_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    labels, embeddings = _labels(engagements), _embeddings(reports)
    # Team 4 has no report vector, so the day has no row for it.
    teams = [2, 3, 4]
    rows = pd.DataFrame({"report_team_id": teams, "snapshot_date": [AS_OF.date()] * len(teams)})
    training = project_context(rows, labels, embeddings)

    # A report born on AS_OF's day reads the day before it, whose as_of is AS_OF.
    key = serving_project_vectors_key("inbox_ranking", (AS_OF.date() - datetime.timedelta(days=1)).isoformat())
    days: dict[str, bytes] = {}
    for kinds in (CONTEXT_KINDS, PROJECT_VECTOR_KINDS):
        buffer = io.BytesIO()
        pq.write_table(project_vectors(labels, embeddings, AS_OF, kinds), buffer)
        days[",".join(kinds)] = buffer.getvalue()
    published = [days[",".join(CONTEXT_KINDS)]]
    monkeypatch.setattr(
        model_store.object_storage,
        "read_bytes",
        lambda name, bucket=None, *, missing_ok=False: published[0] if name == key else None,
    )
    entry = ServingManifestEntry(
        key="nn@2026-07-29",
        model_name="nn",
        model_version="2026-07-29",
        model_kind="onnx",
        roles=[SERVED_ROLE],
        prefix="inbox_ranking/serving/models/nn@2026-07-29",
        heads=["open"],
        model_file="model.onnx",
        reads_project_vectors=True,
    )
    manifest = ServingManifest(manifest_version=AS_OF.isoformat(), models=[entry], project_vectors=key)
    serving = model_store.load_project_vectors(manifest, teams)
    published[0] = days[",".join(PROJECT_VECTOR_KINDS)]
    four_kind_serving = model_store.load_project_vectors(manifest, teams)

    assert serving.kinds == set(CONTEXT_KINDS)
    assert four_kind_serving.missing_kinds(CONTEXT_KINDS) == ["fixed"]
    for position, team_id in enumerate(teams):
        served = serving.for_team(team_id)
        four_kind_served = four_kind_serving.for_team(team_id)
        assert served is not None and four_kind_served is not None
        pair = training.index[position]
        np.testing.assert_array_equal(served.vectors[0], training.vectors[pair])
        np.testing.assert_array_equal(served.has_history[0], training.has_history[pair])
        # A four-kind model gets the same bytes from a five-kind day as from a four-kind day.
        assert served.vectors.tobytes() == four_kind_served.vectors.tobytes()
        assert served.has_history.tobytes() == four_kind_served.has_history.tobytes()
    assert training.has_history[training.index].tolist() == [[1, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    assert not training.vectors[training.index[2]].any()
    fixed_first = serving.for_team(2, ("fixed", "typical"))
    assert fixed_first is not None
    assert fixed_first.has_history.tolist() == [[1, 1]]


LOCAL_REPORT_ID = "00000000-0000-4000-8000-000000000001"
REMOTE_REPORT_ID = "00000000-0000-4000-8000-000000000002"


class _MirrorStorage:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.writes: list[dict[str, Any]] = []

    def write(self, bucket: str, key: str, content: bytes, extras: dict | None) -> None:
        if self.fail:
            raise RuntimeError("mirror unreachable")
        self.writes.append({"bucket": bucket, "key": key, "content": content, "extras": extras})


REMOTE_REPORT_IDS = [f"00000000-0000-4000-8000-00000000001{index}" for index in range(4)]


class _CaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def capture(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def shutdown(self) -> None:
        pass


@pytest.mark.parametrize(
    "mirror_bucket,mirror_fails,label_ids,local_ids,skip_reason",
    [
        ("mirror-bucket", False, [LOCAL_REPORT_ID, REMOTE_REPORT_ID, "not-a-uuid"], {LOCAL_REPORT_ID}, None),
        ("mirror-bucket", True, [LOCAL_REPORT_ID, REMOTE_REPORT_ID, "not-a-uuid"], {LOCAL_REPORT_ID}, None),
        ("", False, [LOCAL_REPORT_ID, REMOTE_REPORT_ID, "not-a-uuid"], {LOCAL_REPORT_ID}, None),
        ("mirror-bucket", False, [LOCAL_REPORT_ID, REMOTE_REPORT_ID], set(), dag.NO_LOCAL_REPORTS),
        (
            "mirror-bucket",
            False,
            [LOCAL_REPORT_ID, *REMOTE_REPORT_IDS],
            {LOCAL_REPORT_ID},
            dag.LOCAL_SHARE_COLLAPSED,
        ),
        ("mirror-bucket", False, [], set(), None),
    ],
    ids=["mirror_set", "mirror_down", "no_mirror", "no_local_reports", "local_share_collapsed", "empty_labels"],
)
def test_the_engagement_export_sends_only_remote_reports_to_the_mirror(
    monkeypatch: pytest.MonkeyPatch,
    mirror_bucket: str,
    mirror_fails: bool,
    label_ids: list[str],
    local_ids: set[str],
    skip_reason: str | None,
) -> None:
    partition_key = BEFORE.date().isoformat()
    labels = pa.Table.from_pylist(
        [
            {"snapshot_date": AS_OF.date(), "report_id": report_id, "first_opened_at": BEFORE, "open_count": 1}
            for report_id in label_ids
        ],
        schema=LABELS_SCHEMA,
    )
    labels_key = common.partition_object_key("inbox_ranking", dag.LABELS_TABLE, partition_key)
    mirror = _MirrorStorage(fail=mirror_fails)
    looked_up: list[list[str]] = []
    capture = _CaptureClient()

    def fake_report_teams(report_ids: list[str], snapshot_end: datetime.datetime) -> dict[str, int]:
        looked_up.append(report_ids)
        return dict.fromkeys(local_ids & set(report_ids), 2)

    def mirror_storage() -> _MirrorStorage:
        assert mirror_bucket, "no mirror is set, so nothing may reach a second store"
        return mirror

    monkeypatch.setattr(dag, "skip_unconfigured", lambda context: False)
    monkeypatch.setattr(dag, "dataset_bucket", lambda: "test-bucket")
    monkeypatch.setattr(dag, "s3_client", lambda: None)
    monkeypatch.setattr(
        dag, "read_parquet", lambda client, bucket, key, columns=None: {labels_key: labels}[key].select(columns)
    )
    monkeypatch.setattr(dag, "_report_teams", fake_report_teams)
    monkeypatch.setattr(dag, "serving_mirror_storage", mirror_storage)
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")
    monkeypatch.setattr(dag.settings, "INBOX_RANKING_SERVING_MIRROR_BUCKET", mirror_bucket)
    monkeypatch.setattr(telemetry, "is_cloud", lambda: True)
    monkeypatch.setattr(telemetry, "get_client", lambda region, **kwargs: capture)

    context = dagster.build_asset_context(partition_key=partition_key)
    dag.inbox_engagement_export(context)

    if not mirror_bucket:
        assert mirror.writes == []
        assert capture.calls == []
        return
    metadata = context.get_output_metadata("result")
    written = not mirror_fails and skip_reason is None
    assert metadata["written"].value is written
    assert ("skip_reason" in metadata) is (skip_reason is not None)
    (event,) = capture.calls
    assert event["event"] == telemetry.ENGAGEMENT_EXPORT_PUBLISHED_EVENT
    local_rows = len(local_ids)
    assert {key: event["properties"][key] for key in ("written", "skip_reason", "excluded_rows", "local_share")} == {
        "written": written,
        "skip_reason": skip_reason,
        "excluded_rows": local_rows,
        "local_share": local_rows / len(label_ids) if label_ids else None,
    }
    assert event["properties"]["partition"] == partition_key
    assert event["properties"]["schema_version"] == dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION
    # No report id and no team id leaves the region through the event.
    assert not {"report_id", "report_ids", "team_id", "team_ids"} & set(event["properties"])
    assert not set(label_ids) & {str(value) for value in event["properties"].values()}

    if not written:
        assert mirror.writes == []
        return
    (write,) = mirror.writes
    assert write["bucket"] == mirror_bucket
    assert write["key"] == serving_engagement_key("inbox_ranking", partition_key)
    # The mirror bucket is in another account, and its policy refuses a write without this ACL.
    assert write["extras"]["ACL"] == "bucket-owner-full-control"
    assert write["extras"]["Metadata"][common.SCHEMA_VERSION_METADATA_KEY] == str(dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION)
    exported = pq.read_table(io.BytesIO(write["content"]))
    assert exported.column_names == list(ENGAGEMENT_EXPORT_COLUMNS)
    if not label_ids:
        assert exported.num_rows == 0
        return
    assert looked_up == [[LOCAL_REPORT_ID, REMOTE_REPORT_ID]]
    assert exported.to_pylist() == [
        dict.fromkeys(ENGAGEMENT_EXPORT_COLUMNS) | {"report_id": REMOTE_REPORT_ID, "first_opened_at": BEFORE}
    ]


class _RegionStorage:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self.objects = objects
        self.writes: list[dict[str, Any]] = []

    def head_object_strict(self, bucket: str, file_key: str) -> dict | None:
        stored = self.objects.get(file_key)
        return None if stored is None else {"Metadata": stored[1]}

    def read_bytes(self, bucket: str, key: str, *, missing_ok: bool = False) -> bytes | None:
        stored = self.objects.get(key)
        return None if stored is None else stored[0]

    def write(self, bucket: str, key: str, content: bytes, extras: dict | None) -> None:
        self.writes.append({"bucket": bucket, "key": key, "content": content, "extras": extras})


def _export_object(engagements: list[tuple[int, int, str, datetime.datetime]], schema_version: int) -> tuple:
    columns = LABEL_COLUMNS if schema_version == 1 else ENGAGEMENT_EXPORT_COLUMNS
    buffer = io.BytesIO()
    pq.write_table(_labels(engagements).select(list(columns)), buffer)
    return buffer.getvalue(), {common.SCHEMA_VERSION_METADATA_KEY: str(schema_version)}


@pytest.mark.parametrize(
    "export_ages,schema_version,expected_export_age",
    [
        ([0, 1], dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION, 0),
        ([1], dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION, 1),
        ([0], 1, 0),
        ([mirror_dag.ENGAGEMENT_EXPORT_MAX_AGE_DAYS + 1], dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION, None),
        ([0], dag.ENGAGEMENT_EXPORT_SCHEMA_VERSION + 1, None),
    ],
    ids=["fresh", "one_day_late", "previous_schema", "too_stale", "unknown_schema"],
)
def test_the_mirror_region_builds_its_vectors_from_its_embeddings_and_the_export(
    monkeypatch: pytest.MonkeyPatch, export_ages: list[int], schema_version: int, expected_export_age: int | None
) -> None:
    partition_day = AS_OF.date() - datetime.timedelta(days=1)
    reports = [(team_id, index, 1.0, BEFORE) for team_id in (5, 9) for index in range(MIN_HISTORY_REPORTS)]
    engagements = [(5, index, "first_opened_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    engagements += [(5, index, "first_fixed_at", BEFORE) for index in range(MIN_HISTORY_REPORTS)]
    storage = _RegionStorage(
        {
            serving_engagement_key(
                "inbox_ranking", (partition_day - datetime.timedelta(days=age)).isoformat()
            ): _export_object(engagements, schema_version)
            for age in export_ages
        }
    )
    read_consent: list[frozenset[int]] = []

    def fake_report_embeddings_table(partition_key: str, rendering: str, consent_team_ids: frozenset[int]) -> pa.Table:
        read_consent.append(consent_team_ids)
        return _embeddings([report for report in reports if report[0] in consent_team_ids])

    monkeypatch.setattr(mirror_dag.object_storage, "object_storage_client", lambda: storage)
    monkeypatch.setattr(mirror_dag, "report_embeddings_table", fake_report_embeddings_table)
    monkeypatch.setattr(mirror_dag, "tag_dagster_queries", lambda context, query_type: None)
    monkeypatch.setattr(mirror_dag, "training_consent_team_ids", lambda: frozenset({5}))
    monkeypatch.setattr(mirror_dag.settings, "INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")
    monkeypatch.setattr(mirror_dag.settings, "OBJECT_STORAGE_BUCKET", "region-bucket")
    context = dagster.build_asset_context(partition_key=partition_day.isoformat())

    if expected_export_age is None:
        with pytest.raises(dagster.Failure):
            mirror_dag.inbox_mirror_project_vectors(context)
        assert storage.writes == []
        return
    mirror_dag.inbox_mirror_project_vectors(context)

    assert read_consent == [frozenset({5})]
    (write,) = storage.writes
    assert write["key"] == serving_project_vectors_key("inbox_ranking", partition_day.isoformat())
    export_date = (partition_day - datetime.timedelta(days=expected_export_age)).isoformat()
    written = pq.read_table(io.BytesIO(write["content"]))
    assert write["extras"]["Metadata"] == {
        common.ROW_COUNT_METADATA_KEY: str(written.num_rows),
        common.SNAPSHOT_DATE_METADATA_KEY: partition_day.isoformat(),
        common.SCHEMA_VERSION_METADATA_KEY: str(PROJECT_VECTORS_SCHEMA_VERSION),
        PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY: export_date,
    }
    # The training region's mirror lookup reads only this metadata, so a key drift drops every day.
    oldest = partition_day - datetime.timedelta(days=training_dag.MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS)
    assert training_dag._project_vectors_refusal(write["extras"]["Metadata"], oldest) is None
    assert written.schema == PROJECT_VECTORS_SCHEMA
    rows = _rows_by_key(written)
    assert {team_id for team_id, _ in rows} == {5}
    assert rows[(5, "open")]["n_reports"] == MIN_HISTORY_REPORTS
    if schema_version == 1:
        assert {kind for _, kind in rows} == set(PROJECT_VECTOR_KINDS)
    else:
        assert rows[(5, "fixed")]["n_reports"] == MIN_HISTORY_REPORTS
    assert set(written.column("as_of").to_pylist()) == {AS_OF}


def test_the_mirror_schedule_skips_until_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mirror_dag.settings, "INBOX_RANKING_MIRROR_PROJECT_VECTORS_ENABLED", False)
    context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2026, 7, 30, 5, 30))

    assert isinstance(mirror_dag.inbox_ranking_mirror_schedule(context), dagster.SkipReason)

    monkeypatch.setattr(mirror_dag.settings, "INBOX_RANKING_MIRROR_PROJECT_VECTORS_ENABLED", True)
    run_request = mirror_dag.inbox_ranking_mirror_schedule(context)

    assert isinstance(run_request, dagster.RunRequest)
    assert run_request.partition_key == "2026-07-29"
