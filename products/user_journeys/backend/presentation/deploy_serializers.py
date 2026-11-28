from datetime import datetime, timedelta

from django.utils import timezone

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    DEPLOY_IDEMPOTENCY_WINDOW_MINUTES,
    MAX_BRANCH_LENGTH,
    MAX_COMMIT_SHA_LENGTH,
    MAX_DEPLOY_LABEL_LENGTH,
    MAX_JOURNEYS_PER_DEPLOY,
    MAX_URL_LENGTH,
    JourneyDeploy,
    JourneyDeployDetail,
    JourneyDeployRun,
    JourneyDeploySkip,
)
from .serializers import validate_run_url

# Clock skew between a CI runner and PostHog. A deploy time further ahead than this is a mistake.
_DEPLOYED_AT_FUTURE_TOLERANCE = timedelta(minutes=5)

_DEPLOY_FIELD_HELP = {
    "id": "Unique identifier of the deploy.",
    "team_id": "Project the deploy belongs to.",
    "commit_sha": "Commit that was deployed.",
    "branch": "Branch that was deployed, when CI sent one.",
    "base_url": (
        "Origin of the build the runs opened, for example a preview deployment. Null when each journey "
        "opened its own start URL."
    ),
    "label": "Short name for the deploy, when CI sent one.",
    "url": "Link to the commit or the CI run, when CI sent one.",
    "deployed_at": "When the build was deployed. Defaults to when PostHog recorded the deploy.",
    "created_at": "When PostHog recorded the deploy.",
    "created_by_id": "ID of the user whose key recorded the deploy. Null for a project secret API key.",
    "status": (
        "Verdict on the deploy's runs. `pending` while no run has started and `running` while any run is "
        "unfinished. `failed` as soon as any run fails, even while others are unfinished. Otherwise, once "
        "every run has ended, `errored` when any run couldn't finish and `passed` when every run passed. "
        "`no_runs` when the deploy started no run. Every status except `pending` and `running` is final."
    ),
    "run_count": "Number of runs the deploy started.",
    "journeys_over_limit": (
        f"Journeys that didn't run because the project has more than {MAX_JOURNEYS_PER_DEPLOY}. "
        "The oldest journeys run first."
    ),
}

_DEPLOY_RUN_FIELD_HELP = {
    "journey_id": "Journey the run replayed.",
    "journey_name": "Name of the journey.",
    "run_id": "The run. Get it from the journey's runs to see each step and its screenshots.",
    "status": "Status of the run: `pending`, `running`, `passed`, `failed` or `errored`.",
    "finished_at": "When the run ended. Null while it is unfinished.",
    "failed_step_index": "Position of the first failed step, from 0. Null unless a step failed.",
    "failure_reason": "Why the first failed step failed. Null unless a step failed.",
    "message": "What went wrong: the failed step's message, or why an errored run couldn't finish.",
}

_DEPLOY_SKIP_FIELD_HELP = {
    "journey_id": "Journey that didn't run.",
    "journey_name": "Name of the journey. Null when the project has no journey with this ID.",
    "reason": (
        "Why the journey didn't run: `journey_not_found`, `not_runnable` when it has no page to start from, "
        "`target_not_allowed` when its start page isn't one of the project's authorized URLs, or "
        "`run_in_progress` when an earlier run of it hasn't finished."
    ),
    "message": "What to change so that the journey runs next time.",
}


class JourneyDeployRunSerializer(DataclassSerializer):
    class Meta:
        dataclass = JourneyDeployRun
        extra_kwargs = {field: {"help_text": text} for field, text in _DEPLOY_RUN_FIELD_HELP.items()}


class JourneyDeploySkipSerializer(DataclassSerializer):
    class Meta:
        dataclass = JourneyDeploySkip
        extra_kwargs = {field: {"help_text": text} for field, text in _DEPLOY_SKIP_FIELD_HELP.items()}


class JourneyDeploySerializer(DataclassSerializer):
    class Meta:
        dataclass = JourneyDeploy
        extra_kwargs = {field: {"help_text": text} for field, text in _DEPLOY_FIELD_HELP.items()}


class JourneyDeployDetailSerializer(DataclassSerializer):
    runs = JourneyDeployRunSerializer(many=True, help_text="One summary for each run the deploy started.")
    skipped = JourneyDeploySkipSerializer(many=True, help_text="Each selected journey that didn't run, and why.")

    class Meta:
        dataclass = JourneyDeployDetail
        extra_kwargs = {field: {"help_text": text} for field, text in _DEPLOY_FIELD_HELP.items()}


class CreateJourneyDeploySerializer(serializers.Serializer):
    commit_sha = serializers.CharField(max_length=MAX_COMMIT_SHA_LENGTH, help_text="Commit that was deployed.")
    branch = serializers.CharField(
        required=False, allow_null=True, max_length=MAX_BRANCH_LENGTH, help_text="Branch that was deployed."
    )
    base_url = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_URL_LENGTH,
        help_text=(
            "Run against this deployment, for example a preview. Only the origin (scheme, host and port) is "
            "used: it replaces the origin of every URL each journey opens and checks. Its host must be one of "
            "the project's authorized URLs. Leave it out to run each journey against its own start URL."
        ),
    )
    deployed_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the build was deployed, in ISO 8601. Defaults to now.",
    )
    label = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_null=True,
        max_length=MAX_DEPLOY_LABEL_LENGTH,
        help_text="Short name for the deploy, for example a release tag.",
    )
    url = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_URL_LENGTH,
        help_text="Link to the commit or the CI run, starting with http:// or https://.",
    )
    journey_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_null=True,
        max_length=MAX_JOURNEYS_PER_DEPLOY,
        help_text=(
            f"Journeys to run, at most {MAX_JOURNEYS_PER_DEPLOY}. Leave it out to run every journey of the "
            f"project, the oldest {MAX_JOURNEYS_PER_DEPLOY} first. Send an empty list to record the deploy "
            "without running any journey. A retry with the same `commit_sha` and `base_url` within "
            f"{DEPLOY_IDEMPOTENCY_WINDOW_MINUTES} minutes returns the first deploy and starts no runs."
        ),
    )

    def validate_base_url(self, value: str | None) -> str | None:
        return validate_run_url(value) or None

    def validate_url(self, value: str | None) -> str | None:
        return validate_run_url(value) or None

    def validate_deployed_at(self, value: datetime | None) -> datetime | None:
        if value is not None and value > timezone.now() + _DEPLOYED_AT_FUTURE_TOLERANCE:
            raise serializers.ValidationError("Enter a deploy time that isn't in the future.")
        return value
