from collections.abc import Mapping
from datetime import date, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.warehouse_object_reads import TRUNCATE_WAREHOUSE_OBJECT_READS_DAILY_TABLES_SQL

from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionSubjectKind
from products.warehouse_suggestions.backend.logic.reads import (
    ReadWindow,
    RollupDays,
    Subject,
    SubjectReads,
    read_rollup_days,
    read_team_reads,
)
from products.warehouse_suggestions.backend.logic.rules import RULES, Surface
from products.warehouse_suggestions.backend.tests.rollup import RollupRead, seed_reads

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
WINDOW = ReadWindow.ending(TODAY, RULES)
FULL_ROLLUP = RollupDays(days_with_data=RULES.window_days, recent_days_with_data=RULES.lifecycle.expire_after_days)

HUMAN = True
BACKGROUND = False

TAG_CASES: list[tuple[str, dict[str, str | int], bool, Surface | None]] = [
    ("mcp", {"source": "mcp"}, HUMAN, Surface.MCP),
    ("cli", {"source": "cli", "scene": ""}, HUMAN, Surface.MCP),
    ("endpoint", {"lc_feature": "endpoint_execution", "scene": ""}, HUMAN, Surface.ENDPOINT),
    ("max_product", {"lc_product": "max_ai", "scene": ""}, HUMAN, Surface.MAX_AI),
    ("max_scene", {"scene": "Max"}, HUMAN, Surface.MAX_AI),
    ("dashboard", {"scene": "Dashboard"}, HUMAN, Surface.DASHBOARD),
    ("insight_feature", {"lc_feature": "insight", "scene": ""}, HUMAN, Surface.INSIGHT),
    ("saved_insights_scene", {"scene": "SavedInsights"}, HUMAN, Surface.INSIGHT),
    ("sql_editor_product", {"lc_product": "sql_editor", "scene": ""}, HUMAN, Surface.SQL_EDITOR),
    ("notebook", {"lc_product": "notebooks", "scene": ""}, HUMAN, Surface.NOTEBOOK),
    ("api_key", {"lc_access_method": "personal_api_key", "scene": ""}, HUMAN, Surface.API),
    ("other_scene", {"scene": "DataWarehouse"}, HUMAN, Surface.PRODUCT_UI),
    ("warehouse_product", {"lc_product": "warehouse", "scene": ""}, HUMAN, Surface.WAREHOUSE),
    ("untagged", {"scene": ""}, HUMAN, Surface.UNKNOWN),
    ("cache_warmup", {"lc_feature": "cache_warmup"}, BACKGROUND, None),
    ("temporal", {"lc_kind": "temporal"}, BACKGROUND, None),
    ("no_user", {"user_id": 0}, BACKGROUND, None),
]


class TestReadTeamReads(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for truncate_sql in TRUNCATE_WAREHOUSE_OBJECT_READS_DAILY_TABLES_SQL():
            sync_execute(truncate_sql)

    def test_rules_classify_each_tag_combination_as_human_or_background_and_by_surface(self) -> None:
        subjects = {name: uuid4() for name, *_ in TAG_CASES}
        seed_reads(
            self.team.pk,
            [
                RollupRead(subject_id=subjects[name], day=YESTERDAY, request_id=name, **tags)  # type: ignore[arg-type]
                for name, tags, *_ in TAG_CASES
            ],
        )

        reads = read_team_reads(self.team.pk, WINDOW, RULES, FULL_ROLLUP)

        classified = {name: _classification(reads.subjects, subjects[name]) for name, *_ in TAG_CASES}
        assert classified == {name: (human, surface) for name, _, human, surface in TAG_CASES}

    def test_counts_requests_people_days_and_median_cost_of_reads_alone_inside_the_window(self) -> None:
        view = uuid4()
        seed_reads(
            self.team.pk + 1, [RollupRead(subject_id=uuid4(), day=TODAY - timedelta(days=3), request_id="other")]
        )
        seed_reads(
            self.team.pk,
            [
                RollupRead(subject_id=view, day=YESTERDAY, request_id="a", user_id=1, read_alone=True, duration_ms=100),
                RollupRead(subject_id=view, day=YESTERDAY, request_id="a", user_id=1, read_alone=True, duration_ms=300),
                RollupRead(subject_id=view, day=TODAY - timedelta(days=2), request_id="b", user_id=2, duration_ms=900),
                RollupRead(subject_id=view, day=TODAY - timedelta(days=40), request_id="old", user_id=3),
                RollupRead(subject_id=view, day=TODAY, request_id="today", user_id=4),
                RollupRead(
                    subject_id=uuid4(),
                    day=YESTERDAY,
                    request_id="table",
                    user_id=5,
                    subject_kind=WarehouseSuggestionSubjectKind.TABLE,
                ),
            ],
        )

        rollup_days = read_rollup_days(WINDOW)
        reads = read_team_reads(self.team.pk, WINDOW, RULES, rollup_days)
        view_reads = reads.subjects[Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=view)]

        assert rollup_days == RollupDays(days_with_data=3, recent_days_with_data=3)
        assert (reads.readers, reads.view_readers, reads.view_reads) == (3, 2, 2)
        assert (view_reads.human_requests, view_reads.human_users, view_reads.human_days) == (2, 2, 2)
        assert (view_reads.human_reads, view_reads.human_duration_ms, view_reads.alone_reads) == (3, 1300, 2)
        assert 100 <= view_reads.alone_duration_ms_median <= 300


def _classification(subjects: Mapping[Subject, SubjectReads], subject_id: UUID) -> tuple[bool, Surface | None]:
    reads = subjects[Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=subject_id)]
    if reads.human_requests == 0:
        return BACKGROUND, None
    (surface,) = reads.requests_by_surface
    return HUMAN, surface
