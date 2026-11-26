from enum import StrEnum

from posthog.dataclasses import frozen

SETUP_CHECK = "Create Visual Review run"
REPORT_CHECK = "Report no Visual Review run needed"


@frozen
class WorkflowConfig:
    reuse_enabled: bool
    bot_shortcut_enabled: bool
    # The skip report refuses to post when the `changes` job cleared the frontend filter by a reuse.
    skip_refuses_after_reuse: bool


MASTER_WORKFLOW = WorkflowConfig(reuse_enabled=True, bot_shortcut_enabled=True, skip_refuses_after_reuse=False)
FIXED_WORKFLOW = WorkflowConfig(reuse_enabled=False, bot_shortcut_enabled=False, skip_refuses_after_reuse=True)


@frozen
class CiInputs:
    # The whole diff of the pull request against its base touches a file the `frontend` filter matches.
    pr_touches_frontend: bool
    # An earlier head of the branch has the same frontend files, and the suite really ran and passed on it.
    proven_head_matches: bool
    # The workflow runs for a push to the pull request (`synchronize`), not for its opening.
    synchronize: bool
    rerun: bool
    # A bot pushed the head, and the push delta holds only the baseline file.
    bot_baseline_only_push: bool
    # Story selection finds a story that the diff affects.
    affected_stories: bool


class CiOutcome(StrEnum):
    CREATE_RUN = "create run"
    REPORT_NO_RUN = "report no run needed"
    REFUSE_REPORT = "refuse the report"


@frozen
class CiDecision:
    outcome: CiOutcome
    reused: bool

    @property
    def setup_conclusion(self) -> str:
        return "success" if self.outcome == CiOutcome.CREATE_RUN else "skipped"

    @property
    def report_conclusion(self) -> str:
        if self.outcome == CiOutcome.REPORT_NO_RUN:
            return "success"
        if self.outcome == CiOutcome.REFUSE_REPORT:
            return "failure"
        return "skipped"


class CiWorkflow:
    """What `ci-storybook.yml` does on a pull request head whose `changes` job and build succeed."""

    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config

    def _reuses(self, inputs: CiInputs) -> bool:
        # paths-filter reuses only on the first attempt of a `synchronize` run.
        if not self.config.reuse_enabled or not inputs.synchronize or inputs.rerun:
            return False
        return inputs.pr_touches_frontend and inputs.proven_head_matches

    def _bot_shortcut(self, inputs: CiInputs) -> bool:
        # The baseline_push step reads the event payload, and a re-run keeps the payload of its push.
        return self.config.bot_shortcut_enabled and inputs.synchronize and inputs.bot_baseline_only_push

    def decide(self, inputs: CiInputs) -> CiDecision:
        reused = self._reuses(inputs)
        frontend = inputs.pr_touches_frontend and not reused and not self._bot_shortcut(inputs)
        # vr-setup runs when select-stories finds a story, and vr-skip when the filter is off or it finds none.
        if frontend and inputs.affected_stories:
            return CiDecision(outcome=CiOutcome.CREATE_RUN, reused=reused)
        if reused and self.config.skip_refuses_after_reuse:
            return CiDecision(outcome=CiOutcome.REFUSE_REPORT, reused=reused)
        return CiDecision(outcome=CiOutcome.REPORT_NO_RUN, reused=reused)
