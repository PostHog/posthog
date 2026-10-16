from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.engineering_analytics.backend.facade.contracts import (
    CIEngine,
    CITimingKind,
    CITimingSampleStatus,
    WorkflowJob,
    WorkflowJobStep,
)
from products.engineering_analytics.backend.logic.ci_timing_context import match_timing_sample, select_timing_jobs
from products.engineering_analytics.backend.logic.queries.timing_candidates import TimingCandidateRun

_START = datetime(2026, 3, 2, 12, tzinfo=UTC)


def _step(number: int, name: str, seconds: int, conclusion: str = "success") -> WorkflowJobStep:
    return WorkflowJobStep(
        number=number,
        name=name,
        status="completed",
        conclusion=conclusion,
        started_at=_START,
        completed_at=_START + timedelta(seconds=seconds),
        duration_seconds=seconds,
    )


def _job(
    job_id: int,
    name: str,
    *,
    seconds: int = 120,
    conclusion: str = "success",
    runner_label: str = "4-core",
    steps: list[WorkflowJobStep] | None = None,
) -> WorkflowJob:
    return WorkflowJob(
        id=job_id,
        run_id=1,
        name=name,
        status="completed",
        conclusion=conclusion,
        started_at=_START,
        completed_at=_START + timedelta(seconds=seconds),
        duration_seconds=seconds,
        runner_provider="self_hosted",
        runner_label=runner_label,
        estimated_cost_usd=None,
        steps=steps or [],
    )


_CURRENT_JOBS = [_job(1, "build", steps=[_step(1, "Set up job", 5), _step(2, "Run tests", 90)]), _job(2, "lint")]
_CANDIDATE_RUN = TimingCandidateRun(
    run_id=900,
    run_attempt=1,
    ci_engine=CIEngine.GITHUB_ACTIONS,
    head_sha="sha900",
    run_started_at=_START,
    native_run_id="900",
    native_workflow_run_id="900",
)
_SUCCESS = CITimingSampleStatus.SUCCESS
_FAILURE = CITimingSampleStatus.FAILURE


class TestMatchTimingSample(SimpleTestCase):
    @parameterized.expand(
        [
            ("job_same_runner", CITimingKind.JOB, [_job(11, "build", seconds=100)], (100.0, _SUCCESS, 11, None)),
            ("job_failed", CITimingKind.JOB, [_job(11, "build", conclusion="failure")], (120.0, _FAILURE, 11, None)),
            ("job_other_runner", CITimingKind.JOB, [_job(11, "build", runner_label="16-core")], None),
            (
                "workflow_same_job_set",
                CITimingKind.WORKFLOW,
                [_job(11, "build", seconds=100), _job(12, "lint", seconds=300)],
                (300.0, _SUCCESS, None, None),
            ),
            ("workflow_changed_job_set", CITimingKind.WORKFLOW, [_job(11, "build")], None),
            ("matrix_changed_job_set", CITimingKind.MATRIX, [_job(11, "build")], None),
            ("job_in_changed_job_set", CITimingKind.JOB, [_job(11, "build")], (120.0, _SUCCESS, 11, None)),
            (
                "workflow_ignores_cancelled_and_skipped_jobs",
                CITimingKind.WORKFLOW,
                [
                    _job(11, "build"),
                    _job(12, "lint"),
                    _job(13, "deploy", conclusion="skipped"),
                    _job(14, "build", conclusion="cancelled", seconds=3),
                ],
                (120.0, _SUCCESS, None, None),
            ),
            (
                "step_by_name_at_another_number",
                CITimingKind.STEP,
                [
                    _job(
                        11,
                        "build",
                        steps=[_step(1, "Set up job", 5), _step(2, "Checkout", 3), _step(3, "Run tests", 70)],
                    )
                ],
                (70.0, _SUCCESS, 11, 3),
            ),
            (
                "step_name_twice_in_job",
                CITimingKind.STEP,
                [_job(11, "build", steps=[_step(2, "Run tests", 70), _step(3, "Run tests", 80)])],
                None,
            ),
        ]
    )
    def test_samples_only_the_same_work(
        self,
        _name: str,
        kind: CITimingKind,
        candidate_jobs: list[WorkflowJob],
        expected: tuple[float, CITimingSampleStatus, int | None, int | None] | None,
    ) -> None:
        selection = select_timing_jobs(
            _CURRENT_JOBS, kind=kind, job_ids=[1], step_number=2 if kind is CITimingKind.STEP else None
        )
        assert selection is not None

        sample = match_timing_sample(_CANDIDATE_RUN, candidate_jobs, selection)

        assert (sample and (sample.duration_seconds, sample.status, sample.job_id, sample.step_number)) == expected
