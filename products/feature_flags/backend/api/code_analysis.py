from typing import Any, cast

from rest_framework import exceptions, serializers, status
from rest_framework.response import Response

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.utils import action
from posthog.models import User
from posthog.permissions import posthog_feature_flag_enabled

from products.feature_flags.backend.code_analysis import (
    CodeAnalysisError,
    CodeAnalysisRepositorySource,
    CodeAnalysisStatus,
    get_code_analysis_status,
    get_code_analysis_target,
    start_code_analysis,
)
from products.feature_flags.backend.code_cleanup import (
    CodeCleanupUnavailableReason,
    get_cleanup_availability,
    get_cleanup_run,
    start_code_cleanup,
)
from products.feature_flags.backend.models import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade

CODE_ANALYSIS_FEATURE_FLAG = "feature-flag-code-analysis"
# The Code tab reads this code to tell a closed gate apart from a flag that was never analyzed.
CODE_ANALYSIS_UNAVAILABLE_CODE = "code_analysis_unavailable"

_ERROR_STATUS = {
    "ai_not_approved": status.HTTP_403_FORBIDDEN,
    "ai_credits_exhausted": status.HTTP_402_PAYMENT_REQUIRED,
    "no_repository": status.HTTP_400_BAD_REQUEST,
    "already_running": status.HTTP_409_CONFLICT,
    "cleanup_unavailable": status.HTTP_400_BAD_REQUEST,
    "cleanup_exists": status.HTTP_409_CONFLICT,
    "outcome_required": status.HTTP_400_BAD_REQUEST,
    "invalid_outcome": status.HTTP_400_BAD_REQUEST,
}


def _validate_repository_name(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise serializers.ValidationError("Repository must be in the format organization/repository")
    return value


class FeatureFlagCodeAnalysisStartSerializer(serializers.Serializer):
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text=(
            "GitHub repository to analyze, as `organization/repository`. It must be connected to the project's "
            "GitHub integration. Omit it to use the repository the last analysis used, the environment's default "
            "flag cleanup repository, or the only connected repository."
        ),
    )

    def validate_repository(self, value: str | None) -> str | None:
        return _validate_repository_name(value)


class FeatureFlagCodeAnalysisTargetQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Repository to check, as `organization/repository`. Omit it to see which repository would be used.",
    )

    def validate_repository(self, value: str | None) -> str | None:
        return _validate_repository_name(value)


class FeatureFlagCodeAnalysisTargetSerializer(serializers.Serializer):
    repository = serializers.CharField(
        allow_null=True,
        help_text="Repository the analysis would read, or null when none can be chosen without asking.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=CodeAnalysisRepositorySource.choices,
        help_text=(
            "How the repository was chosen: `explicit` (the requested one), `previous_analysis` (the one the last "
            "analysis of this flag used), `team_default` (the environment's default flag cleanup repository), "
            "`single_repo` (the only connected repository), `ambiguous` (several connected repositories and none "
            "chosen, so pass one), or `no_integration` (no GitHub integration or no connected repositories)."
        ),
    )
    candidates = serializers.ListField(
        child=serializers.CharField(), help_text="Repositories connected to the project's GitHub integration."
    )


class FeatureFlagCodeBranchSerializer(serializers.Serializer):
    variant = serializers.CharField(
        help_text=(
            'What the flag evaluates to on this branch: "enabled", "disabled", or a variant key. "all" when the '
            "same code runs for every outcome and only the flag value passed to it differs."
        )
    )
    start_line = serializers.IntegerField(help_text="First line of the branch body, 1-based.")
    end_line = serializers.IntegerField(help_text="Last line of the branch body, 1-based and inclusive.")
    snippet = serializers.CharField(
        allow_blank=True, help_text="The branch body as it appears in the file. Empty when the outcome runs no code."
    )


class FeatureFlagCodeReferenceSerializer(serializers.Serializer):
    file = serializers.CharField(help_text="Path of the file from the repository root.")
    check_line = serializers.IntegerField(
        help_text="Line where the flag value decides which code runs (the if, ternary, switch, or call it is passed to), 1-based."
    )
    method = serializers.CharField(help_text="SDK call or wrapper that reads the flag, for example `isFeatureEnabled`.")
    summary = serializers.CharField(help_text="One sentence on what changes when the flag turns on at this check.")
    branches = FeatureFlagCodeBranchSerializer(many=True, help_text="The code that runs for each outcome of the flag.")


class FeatureFlagCodeAnalysisResultSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository that was analyzed, as `organization/repository`.")
    commit_sha = serializers.CharField(help_text="Commit the analysis read.")
    references = FeatureFlagCodeReferenceSerializer(
        many=True, help_text="Every place the flag is checked. Empty when the repository has no references."
    )
    notes = serializers.CharField(
        allow_blank=True, help_text="Caveats from the analysis, such as keys built at runtime or ambiguous checks."
    )


class FeatureFlagCodeCleanupRunSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="ID of the task that opens the cleanup pull request.")
    run_status = serializers.ChoiceField(
        choices=tasks_facade.TaskRunStatus.choices, help_text="Status of the cleanup run."
    )
    is_terminal = serializers.BooleanField(
        help_text="Whether the run has finished, successfully or not. Stop polling once true."
    )
    pr_url = serializers.URLField(
        allow_null=True,
        help_text="The draft pull request the run opened. Null while it runs, or when it found no code to remove.",
    )
    error_message = serializers.CharField(allow_null=True, help_text="Why the run failed, when it failed.")
    can_view_task = serializers.BooleanField(
        help_text="Whether the requesting user can open the task. Hide the task link from everyone else."
    )


class FeatureFlagCodeCleanupSerializer(serializers.Serializer):
    unavailable_reason = serializers.ChoiceField(
        choices=CodeCleanupUnavailableReason.choices,
        allow_null=True,
        help_text=(
            "Why a cleanup pull request can't be opened, or null when it can: `analysis_not_ready` (the analysis "
            "has no result yet), `no_references` (the analysis found no checks to remove), `not_stale` (the flag "
            "is still in use), or `unsupported_config` (the flag's configuration can't be read safely)."
        ),
    )
    suggested_outcome = serializers.CharField(
        allow_null=True,
        help_text=(
            "The outcome every user gets today, whose code the cleanup keeps by default: `enabled`, `disabled`, or "
            "a variant key. Null when users get different outcomes, so the caller must choose one."
        ),
    )
    outcome_options = serializers.ListField(
        child=serializers.CharField(), help_text="Outcomes whose code the cleanup can keep."
    )
    run = FeatureFlagCodeCleanupRunSerializer(
        allow_null=True, help_text="The flag's latest cleanup run, or null when none was requested."
    )


class FeatureFlagCodeCleanupStartSerializer(serializers.Serializer):
    keep_outcome = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=400,
        help_text=(
            "Outcome whose code to keep: `enabled`, `disabled`, or a variant key from `cleanup.outcome_options`. "
            "Omit it to keep `cleanup.suggested_outcome`."
        ),
    )


class FeatureFlagCodeAnalysisSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="ID of the task that runs the analysis.")
    repository = serializers.CharField(help_text="Repository the analysis reads, as `organization/repository`.")
    created_at = serializers.DateTimeField(help_text="When the analysis was requested.")
    run_status = serializers.ChoiceField(
        choices=tasks_facade.TaskRunStatus.choices,
        help_text="Status of the analysis run. A finished run with output in an unexpected shape is reported as failed.",
    )
    is_terminal = serializers.BooleanField(
        help_text="Whether the run has finished, successfully or not. Stop polling once true."
    )
    error_message = serializers.CharField(allow_null=True, help_text="Why the run failed, when it failed.")
    can_view_task = serializers.BooleanField(
        help_text="Whether the requesting user can open the task. Hide the task link from everyone else."
    )
    result = FeatureFlagCodeAnalysisResultSerializer(
        allow_null=True, help_text="The flag's code paths, once the run completes."
    )
    cleanup = FeatureFlagCodeCleanupSerializer(
        help_text="Whether a draft pull request that removes the flag's checks can be opened, and its latest run."
    )


def _serialize_status(flag: FeatureFlag, user: User, analysis_status: CodeAnalysisStatus) -> dict[str, Any]:
    availability = get_cleanup_availability(flag, analysis_status)
    run = get_cleanup_run(flag, user)
    return FeatureFlagCodeAnalysisSerializer(
        {
            "task_id": analysis_status.analysis.task_id,
            "repository": analysis_status.analysis.repository,
            "created_at": analysis_status.analysis.created_at,
            "run_status": analysis_status.run_status,
            "is_terminal": analysis_status.is_terminal,
            "error_message": analysis_status.error_message,
            "can_view_task": analysis_status.can_view_task,
            "result": analysis_status.result.model_dump() if analysis_status.result else None,
            "cleanup": {
                "unavailable_reason": availability.unavailable_reason,
                "suggested_outcome": availability.suggested_outcome,
                "outcome_options": list(availability.outcome_options),
                "run": run,
            },
        }
    ).data


class FeatureFlagCodeAnalysisMixin:
    """Actions that find where a flag is checked in the project's GitHub repository."""

    def _require_code_analysis_enabled(self, request: Any) -> None:
        team = self.team  # type: ignore[attr-defined]
        if not posthog_feature_flag_enabled(
            CODE_ANALYSIS_FEATURE_FLAG,
            str(cast(User, request.user).distinct_id),
            organization_id=team.organization_id,
            team_id=team.id,
        ):
            raise exceptions.NotFound(code=CODE_ANALYSIS_UNAVAILABLE_CODE)

    @extend_schema(request=None, responses={200: FeatureFlagCodeAnalysisSerializer})
    @action(
        methods=["GET"],
        detail=True,
        url_path="code_analysis",
        required_scopes=["feature_flag:read"],
        pagination_class=None,
    )
    def code_analysis(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """
        The latest code analysis of this flag: where the project's GitHub repository checks the flag, and
        the code each outcome runs.

        Poll until `is_terminal` is true. `result` is filled once the run completes. Returns 404 when the
        flag has never been analyzed.
        """
        self._require_code_analysis_enabled(request)
        flag: FeatureFlag = self.get_object()  # type: ignore[attr-defined]
        user = cast(User, request.user)
        analysis_status = get_code_analysis_status(flag, user)
        if analysis_status is None:
            raise exceptions.NotFound("This flag hasn't been analyzed yet.")
        return Response(_serialize_status(flag, user, analysis_status))

    @validated_request(
        FeatureFlagCodeAnalysisStartSerializer,
        responses={
            201: FeatureFlagCodeAnalysisSerializer,
        },
    )
    @action(methods=["POST"], detail=True, url_path="analyze_code", required_scopes=["feature_flag:write"])
    def analyze_code(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """
        Start a read-only analysis of where the project's GitHub repository checks this flag.

        An agent clones the repository, finds every check of the flag, and reports the code each outcome runs.
        It does not change code or the flag. Returns 400 when no repository can be chosen (see
        `code_analysis_target`), 403 when AI data processing is not approved, and 409 when an analysis is
        already running.
        """
        self._require_code_analysis_enabled(request)
        flag: FeatureFlag = self.get_object()  # type: ignore[attr-defined]
        user = cast(User, request.user)
        try:
            start_code_analysis(flag, user, requested_repository=request.validated_data.get("repository"))
        except CodeAnalysisError as error:
            return Response({"detail": str(error), "code": error.code}, status=_ERROR_STATUS[error.code])
        analysis_status = get_code_analysis_status(flag, user)
        assert analysis_status is not None
        return Response(_serialize_status(flag, user, analysis_status), status=status.HTTP_201_CREATED)

    @validated_request(
        FeatureFlagCodeCleanupStartSerializer,
        responses={
            201: FeatureFlagCodeAnalysisSerializer,
        },
    )
    @action(methods=["POST"], detail=True, url_path="open_cleanup_pr", required_scopes=["feature_flag:write"])
    def open_cleanup_pr(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """
        Open a draft pull request that removes this stale flag's checks from the code.

        An agent starts from the checks the latest code analysis found, keeps the code for one outcome, and
        opens the pull request in the repository the analysis read. It does not change the flag. Returns 400
        when the flag isn't stale, the analysis found no checks, or an outcome must be chosen (see
        `cleanup` on `code_analysis`), 403 when AI data processing is not approved, and 409 when a cleanup
        pull request is already open or in progress.
        """
        self._require_code_analysis_enabled(request)
        flag: FeatureFlag = self.get_object()  # type: ignore[attr-defined]
        user = cast(User, request.user)
        try:
            start_code_cleanup(flag, user, keep_outcome=request.validated_data.get("keep_outcome") or None)
        except CodeAnalysisError as error:
            return Response({"detail": str(error), "code": error.code}, status=_ERROR_STATUS[error.code])
        analysis_status = get_code_analysis_status(flag, user)
        assert analysis_status is not None
        return Response(_serialize_status(flag, user, analysis_status), status=status.HTTP_201_CREATED)

    @validated_request(
        query_serializer=FeatureFlagCodeAnalysisTargetQuerySerializer,
        responses={200: FeatureFlagCodeAnalysisTargetSerializer},
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path="code_analysis_target",
        required_scopes=["feature_flag:read"],
        pagination_class=None,
    )
    def code_analysis_target(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """
        Repository a code analysis of this flag would read.

        Resolution order: the requested repository, else the one the last analysis used, else the
        environment's default flag cleanup repository, else the only connected repository. When the
        project has several repositories and none is chosen (`source=ambiguous`), pass one in `repository`.
        """
        self._require_code_analysis_enabled(request)
        flag: FeatureFlag = self.get_object()  # type: ignore[attr-defined]
        target = get_code_analysis_target(flag, requested_repository=request.validated_query_data.get("repository"))
        return Response(
            FeatureFlagCodeAnalysisTargetSerializer(
                {"repository": target.repository, "source": target.source, "candidates": list(target.candidates)}
            ).data
        )
