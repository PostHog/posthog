import io
import datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.shadow.dag import GRADE_SCHEMA, grade_rows, impression_frame, load_scores
from products.signals.dags.inbox_ranking.shadow.metrics import (
    ATTRIBUTION_WINDOW,
    HEURISTIC_ORDER,
    MODEL_ORDER,
    RANDOM_ORDER,
    deduplicate_lists,
    grade_lists,
    join_scores,
    ndcg_at_k,
    reciprocal_rank,
    score_coverage,
    served_lists,
    with_outcomes,
)
from products.signals.dags.inbox_ranking.shadow.queries import IMPRESSION_LISTS_SQL, OUTCOMES_SQL, hogql_rows
from products.signals.dags.inbox_ranking.shadow.telemetry import (
    SHADOW_RANKING_GRADED_EVENT,
    SHADOW_RUN_COMPLETED_EVENT,
    shadow_grade_events,
)
from products.signals.dags.inbox_ranking.training.unseen import UNSEEN_SCORES_TABLE

DAY = datetime.date(2026, 9, 10)
SERVED_AT = datetime.datetime(2026, 9, 10, 12, 0, tzinfo=datetime.UTC)
WINDOW_START = datetime.datetime(2026, 9, 10, tzinfo=datetime.UTC)
WINDOW_END = datetime.datetime(2026, 9, 11, tzinfo=datetime.UTC)
UUID_A = "0198c0e8-93c8-0000-38f5-a934eeb1b93e"
UUID_B = "0198c0e8-93c8-0000-38f5-a934eeb1b93f"


def _lists(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["impressed_at"] = pd.to_datetime(frame["impressed_at"], utc=True)
    return frame


def _served(impression_id: str, report_ids: list[str], *, at: datetime.datetime = SERVED_AT) -> list[dict]:
    return [
        {
            "impression_id": impression_id,
            "distinct_id": "user-1",
            "impressed_at": at,
            "tab": "all",
            "scope": "project",
            "report_id": report_id,
            "served_rank": rank,
            "session_id": "session-1",
            "list_size": len(report_ids),
        }
        for rank, report_id in enumerate(report_ids, start=1)
    ]


def _scores(report_ids: list[str], scores: list[float], *, snapshot_date: datetime.date, head: str = "open"):
    frame = pd.DataFrame(
        {
            "report_id": report_ids,
            "snapshot_date": snapshot_date,
            "model_name": "tabular_xgb",
            "model_version": snapshot_date.isoformat(),
            "model_role": "champion",
            "head": head,
            "score": scores,
        }
    )
    return frame.assign(available_at=pd.Timestamp(snapshot_date, tz="UTC") + datetime.timedelta(days=1, hours=7))


def test_ndcg_rewards_putting_the_engaged_report_first():
    assert ndcg_at_k(np.array([1.0, 0.0, 0.0]), 5) == 1.0
    # Second place pays log2(3) of the ideal.
    assert ndcg_at_k(np.array([0.0, 1.0, 0.0]), 5) == pytest.approx(1 / np.log2(3))
    # A cutoff that excludes the only engaged row scores nothing, which is the point of @k.
    assert ndcg_at_k(np.array([0.0] * 5 + [1.0]), 5) == 0.0
    assert ndcg_at_k(np.array([0.0, 0.0]), 5) == 0.0


def test_reciprocal_rank_is_one_over_the_first_hit():
    assert reciprocal_rank(np.array([0.0, 1.0, 1.0])) == 0.5
    assert reciprocal_rank(np.array([0.0, 0.0])) == 0.0


def test_repeated_renders_only_collapse_inside_the_same_render_window():
    rows = _lists(
        [
            *_served("first", [UUID_A, UUID_B]),
            *_served("duplicate", [UUID_A, UUID_B], at=SERVED_AT + datetime.timedelta(seconds=1)),
            *_served("second", [UUID_A, UUID_B], at=SERVED_AT + datetime.timedelta(minutes=1)),
            *_served("reordered", [UUID_B, UUID_A], at=SERVED_AT + datetime.timedelta(minutes=2)),
            # Hours later the same order is a second visit, not a repeat: an open that follows it
            # lands outside the morning render's attribution window and would be lost with it.
            *_served("revisit", [UUID_A, UUID_B], at=SERVED_AT + datetime.timedelta(hours=5)),
        ]
    )

    outcomes = pd.DataFrame(
        [{"report_id": UUID_A, "distinct_id": "user-1", "timestamp": SERVED_AT + datetime.timedelta(seconds=2)}]
    ).assign(outcome="open")
    kept = deduplicate_lists(with_outcomes(rows, outcomes))

    assert sorted(kept["impression_id"].unique()) == ["duplicate", "reordered", "revisit", "second"]
    assert len(kept) == 8
    assert kept.loc[kept["outcome_open"], "report_id"].tolist() == [UUID_A]


@pytest.mark.parametrize("section_tabs", [("all", "all"), ("monitoring", "needs-decision")])
def test_section_and_pagination_events_reassemble_one_complete_list(section_tabs: tuple[str, str]) -> None:
    rows = _lists(_served("first", [UUID_A, UUID_B]))
    rows["impression_id"] = ["first", "second"]
    rows["tab"] = list(section_tabs)
    rows.loc[1, "impressed_at"] += datetime.timedelta(seconds=2)
    if section_tabs == ("all", "all"):
        rows.loc[0, "list_size"] = 1

    assembled = deduplicate_lists(rows)

    assert assembled["impression_id"].nunique() == 1
    assert assembled["report_id"].tolist() == [UUID_A, UUID_B]
    assert assembled["served_rank"].tolist() == [1, 2]
    assert assembled["list_size"].tolist() == [2, 2]


@pytest.mark.parametrize(
    "variation", ["missing_row", "next_bucket", "different_session", "rank_conflict", "missing_session"]
)
def test_incomplete_or_conflicting_render_windows_are_excluded(variation: str) -> None:
    rows = _lists(_served("first", [UUID_A, UUID_B]))
    if variation == "missing_row":
        rows = rows.head(1)
    elif variation == "next_bucket":
        rows.loc[1, "impressed_at"] += datetime.timedelta(seconds=5)
    elif variation == "different_session":
        rows.loc[1, "session_id"] = "session-2"
    elif variation == "missing_session":
        rows["session_id"] = ""
    else:
        rows.loc[1, "served_rank"] = 1

    assert deduplicate_lists(rows).empty


def test_an_engagement_counts_for_the_list_that_preceded_it():
    rows = _lists(_served("first", [UUID_A, UUID_B]))
    outcomes = pd.DataFrame(
        [
            {"report_id": UUID_A, "distinct_id": "user-1", "timestamp": SERVED_AT + datetime.timedelta(minutes=2)},
            # Too late to be this list's doing, and a different person's open is never this one's.
            {"report_id": UUID_B, "distinct_id": "user-1", "timestamp": SERVED_AT + ATTRIBUTION_WINDOW},
            {"report_id": UUID_B, "distinct_id": "user-2", "timestamp": SERVED_AT + datetime.timedelta(minutes=2)},
        ]
    ).assign(outcome="open")

    engaged = with_outcomes(rows, outcomes)

    assert engaged.set_index("report_id")["outcome_open"].to_dict() == {UUID_A: True, UUID_B: False}
    assert not engaged["outcome_action"].any()


def test_an_engagement_is_credited_to_one_list_only():
    # Changing a filter or a sort re-impresses the same rows at new ranks, so one person can hold
    # several live lists holding the same report. Only the last one they saw it in caused the open.
    rows = _lists(
        [
            *_served("first", [UUID_A, UUID_B]),
            *_served("reordered", [UUID_B, UUID_A], at=SERVED_AT + datetime.timedelta(minutes=1)),
        ]
    )
    outcomes = pd.DataFrame(
        [{"report_id": UUID_A, "distinct_id": "user-1", "timestamp": SERVED_AT + datetime.timedelta(minutes=2)}]
    ).assign(outcome="open")

    engaged = with_outcomes(rows, outcomes)

    credited = engaged.loc[engaged["outcome_open"], ["impression_id", "report_id"]]
    assert credited.to_numpy().tolist() == [["reordered", UUID_A]]

    incomplete = rows.loc[~((rows["impression_id"] == "reordered") & (rows["report_id"] == UUID_B))]
    complete = deduplicate_lists(with_outcomes(incomplete, outcomes))
    assert complete["impression_id"].unique().tolist() == ["first"]
    assert not complete["outcome_open"].any()


def test_a_list_only_uses_scores_that_already_existed_when_it_was_served():
    rows = _lists(_served("first", [UUID_A, UUID_B]))
    scores = pd.concat(
        [
            _scores([UUID_A], [0.9], snapshot_date=DAY - datetime.timedelta(days=3)).assign(
                available_at=SERVED_AT - datetime.timedelta(hours=1)
            ),
            _scores([UUID_A], [0.4], snapshot_date=DAY - datetime.timedelta(days=1)),
            # A report born on the day it was impressed: the daily job that scores it has not run.
            _scores([UUID_B], [0.8], snapshot_date=DAY),
        ],
        ignore_index=True,
    )

    joined = join_scores(rows, scores)

    assert joined["report_id"].tolist() == [UUID_A, UUID_B]
    assert joined["score"].iloc[0] == 0.4
    assert pd.isna(joined["score"].iloc[1])
    assert score_coverage(len(rows), joined) == 0.5


def test_lists_without_an_outcome_or_a_choice_to_make_are_not_graded():
    rows = _lists([*_served("no_outcome", [UUID_A, UUID_B]), *_served("single", [UUID_A])])
    graded = rows.assign(outcome_open=[False, False, True], score=0.5, head="open")

    assert served_lists(graded, "open") == []


def test_the_model_order_is_graded_against_the_served_order_and_chance():
    # The served order buries the only report anyone opened; the model scores it highest.
    served = _lists(_served("first", [UUID_A, UUID_B, UUID_B + "-c", UUID_B + "-d"])).assign(
        outcome_open=[False, False, False, True], outcome_action=False
    )
    joined = served.assign(
        model_name="tabular_xgb",
        model_version="2026-09-09",
        model_role="champion",
        head="open",
        score=[0.1, 0.2, 0.3, 0.9],
    )

    grades = {grade.ranking_order: grade for grade in grade_lists(joined, served=served)}
    ndcg_5 = {order: grade.ndcg_5 or 0.0 for order, grade in grades.items()}

    assert grades[MODEL_ORDER].mrr == 1.0
    assert grades[HEURISTIC_ORDER].mrr == 0.25
    assert ndcg_5[MODEL_ORDER] == 1.0
    assert ndcg_5[MODEL_ORDER] > ndcg_5[RANDOM_ORDER] > ndcg_5[HEURISTIC_ORDER]
    # Only the random line carries a spread: the other two are one deterministic ordering.
    assert (grades[RANDOM_ORDER].mrr_std or 0.0) > 0
    assert grades[MODEL_ORDER].mrr_std is None
    # The served rank of the opened report, which is how much position bias these numbers carry.
    assert grades[MODEL_ORDER].positive_served_rank_mean == 4.0
    assert {grade.outcome for grade in grade_lists(joined, served=served)} == {"open"}


def test_a_grade_carries_its_own_score_coverage_not_the_run_s():
    # A head is scored only on the partitions the training job found it readable on, so one head
    # can rest on far fewer of a day's served rows than another. The run figure hides that.
    served = _lists(_served("first", [UUID_A, UUID_B, UUID_B + "-c", UUID_B + "-d"])).assign(
        outcome_open=[True, False, False, False], outcome_action=[True, False, False, False]
    )
    scored = {"model_name": "tabular_xgb", "model_version": "2026-09-09", "model_role": "champion", "score": 0.5}
    joined = pd.concat(
        [served.assign(head="open", **scored), served.head(2).assign(head="action", **scored)],
        ignore_index=True,
    )

    coverage = {
        (grade.outcome, grade.ranking_order): grade.score_coverage for grade in grade_lists(joined, served=served)
    }

    assert score_coverage(len(served), joined) == 1.0
    assert coverage[("open", MODEL_ORDER)] == 1.0
    assert coverage[("action", MODEL_ORDER)] == 0.5


def test_the_chance_line_does_not_move_when_the_rows_arrive_in_another_order():
    # The impression query has no ORDER BY, so a re-run can hand the same rows over differently.
    # The seeded permutations are applied to the array as it stands, and the partition is history.
    served = _lists(_served("first", [UUID_A, UUID_B, UUID_B + "-c", UUID_B + "-d"])).assign(
        outcome_open=[False, True, False, True], outcome_action=False
    )
    joined = served.assign(
        model_name="tabular_xgb",
        model_version="2026-09-09",
        model_role="champion",
        head="open",
        score=[0.1, 0.2, 0.3, 0.9],
    )

    def chance(frame: pd.DataFrame) -> tuple:
        grade = next(g for g in grade_lists(frame, served=served) if g.ranking_order == RANDOM_ORDER)
        return (grade.ndcg_5, grade.ndcg_10, grade.mrr)

    assert chance(joined.iloc[[3, 0, 2, 1]]) == chance(joined)


def test_a_grade_keeps_unscored_positives_and_ranks_them_last():
    served = _lists(
        [
            *_served("kept", [UUID_A, UUID_B, UUID_B + "-c"]),
            *_served("dropped", [UUID_B + "-d", UUID_B + "-e"], at=SERVED_AT + datetime.timedelta(hours=2)),
        ]
    ).assign(outcome_open=[True, False, False, True, False], outcome_action=False)
    joined = join_scores(served, _scores([UUID_A, UUID_B], [0.9, 0.1], snapshot_date=DAY - datetime.timedelta(days=1)))

    grade = next(grade for grade in grade_lists(joined, served=served) if grade.ranking_order == MODEL_ORDER)

    assert grade.lists == 2
    assert grade.reports == 5
    assert grade.positive_coverage == 0.5
    assert grade.full_list_coverage == 0.0
    assert grade.score_coverage == 0.4
    assert grade.mrr == 1.0

    served["outcome_open"] = [False, False, True, True, False]
    joined = join_scores(served, _scores([UUID_A, UUID_B], [0.9, 0.1], snapshot_date=DAY - datetime.timedelta(days=1)))
    grade = next(grade for grade in grade_lists(joined, served=served) if grade.ranking_order == MODEL_ORDER)
    assert grade.mrr == pytest.approx((1 / 3 + 1) / 2)
    assert grade.positive_coverage == 0.0


def test_a_grade_carries_the_versions_that_scored_the_day():
    served = _lists([*_served("first", [UUID_A, UUID_B]), *_served("second", [UUID_A, UUID_B])]).assign(
        outcome_open=[True, False, True, False], outcome_action=False
    )
    joined = served.assign(
        model_name="tabular_xgb",
        model_version=["2026-09-01", "2026-09-02", "2026-09-01", "2026-09-02"],
        model_role="champion",
        head="open",
        score=0.5,
    )

    assert {grade.model_versions for grade in grade_lists(joined, served=served)} == {2}


class TestShadowQueries(ClickhouseTestMixin, BaseTest):
    def _impress(
        self,
        impressions: list[dict],
        *,
        distinct_id: str = "user-1",
        at=SERVED_AT,
        tab: str = "all",
        list_size: int | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="Inbox reports impressed",
            distinct_id=distinct_id,
            timestamp=at,
            properties={
                "tab": tab,
                "scope": "project",
                "impressions": impressions,
                "$session_id": "0198c0e8-93c8-7000-8000-a934eeb1b940",
                "list_size": len(impressions) if list_size is None else list_size,
            },
        )

    def _rows(self, sql: str) -> list[tuple]:
        return hogql_rows(
            sql,
            team=self.team,
            query_type="test",
            window_start=WINDOW_START,
            window_end=WINDOW_END + ATTRIBUTION_WINDOW,
        )

    def test_one_impression_event_is_one_ranked_list(self):
        self._impress([{"report_id": UUID_A, "rank": 1}, {"report_id": UUID_B, "rank": 2}])
        self._impress([{"report_id": UUID_A, "rank": 1}], distinct_id="user-2")

        rows = deduplicate_lists(impression_frame(self._rows(IMPRESSION_LISTS_SQL))).to_numpy().tolist()

        lists = {row[0] for row in rows}
        assert len(lists) == 2
        by_report = {(row[0], row[5]): row[6] for row in rows}
        assert sorted(by_report.values()) == [1, 1, 2]

    def test_merged_sections_reconstruct_the_render_and_exclude_an_incomplete_visit(self) -> None:
        self._impress([{"report_id": UUID_A, "rank": 1}], tab="monitoring", list_size=2)
        self._impress(
            [{"report_id": UUID_B, "rank": 2}],
            tab="needs-decision",
            list_size=2,
            at=SERVED_AT + datetime.timedelta(seconds=1),
        )
        self._impress([{"report_id": UUID_A, "rank": 1}], distinct_id="user-2", list_size=2)

        rows = deduplicate_lists(impression_frame(self._rows(IMPRESSION_LISTS_SQL)))

        assert rows["impression_id"].nunique() == 1
        assert rows.sort_values("served_rank")["report_id"].tolist() == [UUID_A, UUID_B]
        assert rows["list_size"].tolist() == [2, 2]

    def test_a_report_with_no_usable_rank_cannot_be_placed_in_the_served_order(self):
        # Ranks are client-supplied; the producer contract is 1-based, so 0 is malformed.
        self._impress([{"report_id": UUID_A, "rank": 0}, {"report_id": UUID_B, "rank": 1}])

        assert [row[5] for row in self._rows(IMPRESSION_LISTS_SQL)] == [UUID_B]

    def test_opens_and_the_action_head_are_the_only_outcomes_read(self):
        for action_type in ("create_pr", "discuss", "snooze"):
            _create_event(
                team=self.team,
                event="Inbox report action",
                distinct_id="user-1",
                timestamp=SERVED_AT,
                properties={"report_id": UUID_A, "action_type": action_type},
            )
        _create_event(
            team=self.team,
            event="Inbox report opened",
            distinct_id="user-1",
            timestamp=SERVED_AT,
            properties={"report_id": UUID_A},
        )

        outcomes = sorted(row[3] for row in self._rows(OUTCOMES_SQL))

        assert outcomes == ["action", "action", "open"]


class _FakeS3:
    """The scores objects of a lookback window, keyed by their S3 key."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_object(self, Bucket: str, Key: str) -> dict:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key]), "LastModified": SERVED_AT + datetime.timedelta(hours=1)}


def _scores_object(frame: pd.DataFrame) -> bytes:
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), sink)
    return sink.getvalue()


def test_load_scores_reads_the_window_and_names_the_family_of_older_objects():
    old_day, new_day = DAY - datetime.timedelta(days=2), DAY - datetime.timedelta(days=1)
    # An object written before `model_name` existed holds tabular rows and must not read as null.
    legacy = _scores([UUID_A], [0.3], snapshot_date=old_day).drop(columns=["model_name", "available_at"])
    recent = pd.concat(
        [
            _scores([UUID_B], [0.7], snapshot_date=new_day).drop(columns=["available_at"]),
            _scores([UUID_B], [0.2], snapshot_date=new_day, head="pr_merged").drop(columns=["available_at"]),
        ],
        ignore_index=True,
    )
    client = _FakeS3(
        {
            partition_object_key("inbox_ranking", UNSEEN_SCORES_TABLE, old_day.isoformat()): _scores_object(legacy),
            partition_object_key("inbox_ranking", UNSEEN_SCORES_TABLE, new_day.isoformat()): _scores_object(recent),
        }
    )

    scores = load_scores(client, "bucket", "inbox_ranking", [old_day, new_day, DAY])

    assert scores["model_name"].tolist() == ["tabular_xgb", "tabular_xgb"]
    # Only the heads this read grades, and each one stamped with when it became servable.
    assert scores["head"].tolist() == ["open", "open"]
    assert scores["available_at"].tolist() == [SERVED_AT + datetime.timedelta(hours=1)] * 2
    joined = join_scores(_lists(_served("first", [UUID_A, UUID_B])), scores)
    assert joined["score"].isna().all()


def test_missing_champion_partition_uses_candidate_without_replacing_existing_champion() -> None:
    old_day, new_day = DAY - datetime.timedelta(days=2), DAY - datetime.timedelta(days=1)
    shared = _scores([UUID_A], [0.3], snapshot_date=old_day).assign(model_role="candidate")
    separate = pd.concat(
        [
            _scores([UUID_B], [0.7], snapshot_date=new_day),
            _scores([UUID_B], [0.2], snapshot_date=new_day).assign(model_role="candidate"),
        ]
    )
    client = _FakeS3(
        {
            partition_object_key("inbox_ranking", UNSEEN_SCORES_TABLE, old_day.isoformat()): _scores_object(shared),
            partition_object_key("inbox_ranking", UNSEEN_SCORES_TABLE, new_day.isoformat()): _scores_object(separate),
        }
    )

    scores = load_scores(client, "bucket", "inbox_ranking", [old_day, new_day])

    champion = scores.loc[scores["model_role"] == "champion"]
    assert champion["report_id"].tolist() == [UUID_A, UUID_B]
    assert champion["score"].tolist() == [0.3, 0.7]


def test_a_day_that_graded_nothing_still_reports_a_run():
    # A day whose lists had no score available at impression time grades nothing, and without a
    # run event that is byte-identical to a run that crashed before capturing anything.
    served = _lists(_served("first", [UUID_A, UUID_B])).assign(outcome_open=[True, False], outcome_action=False)
    joined = served.assign(
        model_name="tabular_xgb",
        model_version="2026-09-09",
        model_role="champion",
        head="open",
        score=[0.9, 0.1],
    )

    empty = shadow_grade_events(run_id="run-1", served_rows=12, served_lists=3, run_score_coverage=0.0, grades=[])
    graded = shadow_grade_events(
        run_id="run-1",
        served_rows=2,
        served_lists=1,
        run_score_coverage=1.0,
        grades=grade_lists(joined, served=served),
    )

    assert [event.event for event in empty] == [SHADOW_RUN_COMPLETED_EVENT]
    assert empty[0].properties == {
        "run_id": "run-1",
        "served_rows": 12,
        "served_lists": 3,
        "run_score_coverage": 0.0,
        "grades": 0,
        "reason": "no_available_scores",
    }
    # The run event rides alongside the three orders, never instead of them.
    assert [event.event for event in graded] == [SHADOW_RUN_COMPLETED_EVENT, *[SHADOW_RANKING_GRADED_EVENT] * 3]


def test_grade_rows_match_the_parquet_schema_exactly():
    # pa.Table.from_pylist drops keys the schema does not name, so a grade field added without a
    # column would vanish from the object without failing anything.
    served = _lists(_served("first", [UUID_A, UUID_B])).assign(outcome_open=[True, False], outcome_action=False)
    joined = served.assign(
        model_name="tabular_xgb",
        model_version="2026-09-09",
        model_role="champion",
        head="open",
        score=[0.9, 0.1],
    )
    graded = grade_rows(
        grade_lists(joined, served=served),
        partition_key=DAY.isoformat(),
        served_rows=2,
        served_lists=1,
        run_coverage=1.0,
    )

    assert set(graded[0]) == set(GRADE_SCHEMA.names)
    assert pa.Table.from_pylist(graded, schema=GRADE_SCHEMA).num_rows == 3
