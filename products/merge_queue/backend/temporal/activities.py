"""Trial-workflow activities.

The durable steps a trial runs through: mark it running, run the **full suite** against the
projected state, then record the verdict back into the engine lifecycle.

`run_full_suite` is the injectable CI-runner seam. Real PostHog-CI dispatch lands later (the
affected-target graph + `ci/scoping.py` full-suite-vs-subset split); for now the seam is a
stub so the orchestration is in place and testable. The full suite — no test selection — is
the correctness invariant and is never configurable here.
"""

from dataclasses import dataclass, field

from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.merge_queue.backend.engine import lifecycle
from products.merge_queue.backend.models import Trial, TrialState


@dataclass
class TrialRef:
    trial_id: int


@dataclass
class SuiteResult:
    passed: bool
    failing_tests: list[str] = field(default_factory=list)
    ci_run_ref: str | None = None


@dataclass
class RecordResultInput:
    trial_id: int
    passed: bool
    failing_tests: list[str] = field(default_factory=list)


@activity.defn
@close_db_connections
def mark_trial_running(ref: TrialRef) -> None:
    Trial.objects.filter(id=ref.trial_id).update(state=TrialState.RUNNING, started_at=timezone.now())


@activity.defn
@close_db_connections
def run_full_suite(ref: TrialRef) -> SuiteResult:
    """Run the full CI suite against the trial's projected state and return the verdict.

    TODO: dispatch the real full-suite CI run (affected-target scope for the partition,
    no test selection) and resolve its result. Until then this raises so a misconfigured
    production worker fails loudly rather than silently passing a PR; tests inject a fake.
    """
    raise NotImplementedError("full-suite CI dispatch is not wired yet; inject a runner in tests")


@activity.defn
@close_db_connections
def record_trial_result(result: RecordResultInput) -> None:
    lifecycle.on_trial_finished(result.trial_id, passed=result.passed, failing_tests=result.failing_tests)
