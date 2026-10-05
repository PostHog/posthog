from parameterized import parameterized

from products.engineering_analytics.backend.facade.contracts import WorkflowJobStep
from products.engineering_analytics.backend.logic.job_logs.badges import parse_job_log

_STEP_NAMES = [
    "Set up job",
    "Fetch code",
    "Restore packages",
    "Prepare database",
    "Post Restore packages",
    "Complete job",
]
_RESTORE, _DATABASE = 3, 4


def _steps(skipped: tuple[int, ...] = ()) -> list[WorkflowJobStep]:
    return [
        WorkflowJobStep(
            number=number,
            name=name,
            status="completed",
            conclusion="skipped" if number in skipped else "success",
            started_at=None,
            completed_at=None,
            duration_seconds=None,
        )
        for number, name in enumerate(_STEP_NAMES, start=1)
    ]


def _log(restore: list[str], database: list[str] | None = None) -> str:
    lines = [
        "2026-01-05T10:00:00.0000000Z Runner image ready",
        "2026-01-05T10:00:01.0000000Z ##[group]Run example/fetch-code@v1",
        "##[group]Run example/restore-packages@v1",
        # A composite action's inner steps are not steps of the job.
        "##[start-action display=Inner;id=inner]",
        "##[group]Run echo inner",
        "##[end-action id=inner]",
        *restore,
        *(["##[group]Run ./bin/prepare-database", *database] if database is not None else []),
        "Post job cleanup.",
    ]
    return "\n".join(lines)


def _flat(badges: list) -> list[tuple[str, str, int, list[str]]]:
    return [(badge.kind.value, badge.state.value, badge.count, badge.detail) for badge in badges]


class TestParseJobLog:
    @parameterized.expand(
        [
            ("hit", ["\x1b[36mCache hit for: packages-a1\x1b[0m"], [("cache", "hit", 1, ["packages-a1"])]),
            ("older_cache", ["Cache hit for restore-key: packages-"], [("cache", "partial", 1, ["packages-"])]),
            (
                "miss",
                ["2026-01-05T10:00:02.0000000Z Cache not found for input keys: packages-a1, packages-"],
                [("cache", "miss", 1, ["packages-a1, packages-"])],
            ),
            (
                "restore_failed_hides_its_own_hit_and_miss",
                [
                    "Cache hit for: packages-a1",
                    "##[warning]Failed to restore: download stopped",
                    "Cache not found for input keys: packages-a1",
                ],
                [("cache", "failed", 1, ["download stopped"])],
            ),
        ]
    )
    def test_cache_outcome_lands_on_the_restoring_step(
        self, _name: str, restore: list[str], expected: list[tuple[str, str, int, list[str]]]
    ) -> None:
        insights = parse_job_log(_log(restore, database=["  No migrations to apply."]), _steps())

        assert insights.log_read and insights.attributed_to_steps
        by_step = {step.number: _flat(step.badges) for step in insights.steps}
        assert by_step == {_RESTORE: expected, _DATABASE: [("migrations", "none", 1, [""])]}
        assert _flat(insights.job) == [*expected, ("migrations", "none", 1, [""])]

    def test_counts_applied_migrations(self) -> None:
        applied = ["  Applying shop.0002_widget... OK", "  Applying shop.0003_widget_color... OK"]

        insights = parse_job_log(_log([], database=applied), _steps())

        assert [(step.number, _flat(step.badges)) for step in insights.steps] == [
            (_DATABASE, [("migrations", "applied", 2, ["shop.0002_widget", "shop.0003_widget_color"])])
        ]

    @parameterized.expand(
        [
            ("log_opens_fewer_steps_than_the_job_ran", None, ()),
            ("log_opens_a_step_the_job_reports_skipped", ["  No migrations to apply."], (_DATABASE,)),
        ]
    )
    def test_reports_job_level_badges_only_when_markers_and_steps_disagree(
        self, _name: str, database: list[str] | None, skipped: tuple[int, ...]
    ) -> None:
        insights = parse_job_log(_log(["Cache hit for: packages-a1"], database=database), _steps(skipped))

        assert insights.log_read and not insights.attributed_to_steps
        assert insights.steps == []
        assert ("cache", "hit", 1, ["packages-a1"]) in _flat(insights.job)
