from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    MAX_BRANCH_LENGTH,
    MAX_COMMIT_SHA_LENGTH,
    MAX_URL_LENGTH,
    MAX_VIEWPORT_HEIGHT,
    MAX_VIEWPORT_WIDTH,
    MIN_VIEWPORT_SIDE,
    JourneyRun,
    JourneyRunDetail,
    JourneyRunStep,
)
from .serializers import JourneyStepField, validate_run_url

_RUN_FIELD_HELP = {
    "id": "Unique identifier of the run.",
    "team_id": "Project the run belongs to.",
    "journey_id": "Journey the run replayed.",
    "trigger": "What started the run: `manual` for a person, `deploy` for a deployment.",
    "status": (
        "`pending` until a worker picks the run up, then `running`. It ends as `passed` when every step "
        "passed, `failed` when a step failed, or `errored` when the run couldn't finish, for example "
        "because no browser was available."
    ),
    "start_url": "URL the browser opened first, after `base_url` replaced its origin. Null until the run starts.",
    "base_url": (
        "Origin that replaced the journey's recorded origin, so the same paths ran against another "
        "deployment, for example a preview. Null when the run used the recorded origin."
    ),
    "commit_sha": "Commit of the deployment the run checked, when the trigger sent one.",
    "branch": "Branch of the deployment the run checked, when the trigger sent one.",
    "viewport_width": "Browser viewport width in CSS pixels.",
    "viewport_height": "Browser viewport height in CSS pixels.",
    "error": "Why an `errored` run couldn't finish. Null for every other status.",
    "baseline_run_id": (
        "The run this run's screenshots were compared with: the newest earlier passed run of the same "
        "journey at the same viewport. Null when there was none."
    ),
    "created_by_id": "ID of the user who started the run, if a user did.",
    "created_at": "When the run was created.",
    "started_at": "When a worker started the run.",
    "finished_at": "When the run ended.",
    "deploy_id": "The deploy that started the run. Null for a run a person started.",
    "failed_step_index": "Position of the first failed step, from 0. Null unless a step failed.",
    "failure_reason": "Why the first failed step failed. Null unless a step failed.",
}

_STEP_FIELD_HELP = {
    "index": "Position of the step in the journey, from 0.",
    "status": (
        "`passed` or `failed`, or `skipped` when an earlier step failed, because later steps can't run "
        "from the wrong page."
    ),
    "failure_reason": "Why a `failed` step failed. Null for other statuses.",
    "message": "What happened at the step, in words. Empty for a step that passed without notes.",
    "screenshot_url": (
        "Short-lived URL of the viewport screenshot. A click step is captured before the click, and a "
        "failed step is captured as the run found the page."
    ),
    "baseline_screenshot_url": "Short-lived URL of the same step's screenshot in the baseline run, if compared.",
    "diff_screenshot_url": "Short-lived URL of an image that marks the pixels that changed from the baseline.",
    "diff_percentage": "Percentage of pixels that changed from the baseline screenshot, from 0 to 100.",
    "visual_change": (
        "`unchanged` or `changed` compared with the baseline, or `new` when the baseline has no screenshot "
        "of the same step. A visual change never fails a run."
    ),
    "duration_ms": "Milliseconds the step took. Null for a skipped step.",
}


class JourneyRunSerializer(DataclassSerializer):
    class Meta:
        dataclass = JourneyRun
        extra_kwargs = {field: {"help_text": text} for field, text in _RUN_FIELD_HELP.items()}


class JourneyRunStepSerializer(DataclassSerializer):
    step = JourneyStepField(help_text="The step as it was defined when the run started.")

    class Meta:
        dataclass = JourneyRunStep
        extra_kwargs = {field: {"help_text": text} for field, text in _STEP_FIELD_HELP.items()}


class JourneyRunDetailSerializer(DataclassSerializer):
    steps = JourneyRunStepSerializer(many=True, help_text="Every step of the run, in order. Empty until it ends.")

    class Meta:
        dataclass = JourneyRunDetail
        extra_kwargs = {field: {"help_text": text} for field, text in _RUN_FIELD_HELP.items()}


class CreateJourneyRunSerializer(serializers.Serializer):
    base_url = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_URL_LENGTH,
        help_text=(
            "Run against another deployment of the same site, for example a preview. Only the origin "
            "(scheme, host and port) is used: it replaces the origin of every URL the journey opens and "
            "checks. Its host must be one of the project's authorized URLs."
        ),
    )
    commit_sha = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_COMMIT_SHA_LENGTH,
        help_text="Commit of the deployment under test, kept on the run for reference.",
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_BRANCH_LENGTH,
        help_text="Branch of the deployment under test, kept on the run for reference.",
    )
    viewport_width = serializers.IntegerField(
        required=False,
        default=DEFAULT_VIEWPORT_WIDTH,
        min_value=MIN_VIEWPORT_SIDE,
        max_value=MAX_VIEWPORT_WIDTH,
        help_text=f"Browser viewport width in CSS pixels, from {MIN_VIEWPORT_SIDE} to {MAX_VIEWPORT_WIDTH}.",
    )
    viewport_height = serializers.IntegerField(
        required=False,
        default=DEFAULT_VIEWPORT_HEIGHT,
        min_value=MIN_VIEWPORT_SIDE,
        max_value=MAX_VIEWPORT_HEIGHT,
        help_text=f"Browser viewport height in CSS pixels, from {MIN_VIEWPORT_SIDE} to {MAX_VIEWPORT_HEIGHT}.",
    )

    def validate_base_url(self, value: str | None) -> str | None:
        return validate_run_url(value) or None
