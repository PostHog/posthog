from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import ErrorTrackingIssue, sync_issues_to_clickhouse
from products.ml_inference.backend.facade import api as ml_inference
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

SEVERITY_INFERENCE_FLAG = "error-tracking-severity-inference"
SEVERITY_INFERENCE_MODEL = "posthog/hogference/jevk5-fp8-0.2"

_SEVERITY_QUESTION_ID = "severity"
_SEVERITY_QUESTION = DecisionQuestion(
    type=DecisionQuestionType.CHOICE,
    instructions="How severe is this error for the people using the application?",
    criteria={
        ErrorTrackingIssue.Severity.CRITICAL.value: "Crashes the app, loses data, or blocks a core flow such as sign-in, checkout or payment",
        ErrorTrackingIssue.Severity.HIGH.value: "Breaks a feature for the users who hit it, with no workaround",
        ErrorTrackingIssue.Severity.MEDIUM.value: "Degrades a feature, or the app recovers or retries on its own",
        ErrorTrackingIssue.Severity.LOW.value: "Noise with no user impact, such as expected errors, cancelled requests, or browser extension and third-party script errors",
    },
)


def severity_inference_enabled(team_id: int) -> bool:
    # The analytics SDK is disabled in local dev, so the flag always reads as off there.
    if settings.DEBUG:
        return True
    try:
        return feature_enabled_or_false(
            SEVERITY_INFERENCE_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("error_tracking_severity_inference_flag_check_failed", team_id=team_id)
        return False


def build_severity_state(stacktrace: str, event_properties: dict[str, object]) -> str:
    lines = [stacktrace.rstrip("\n")]
    handled = _mechanism_handled(event_properties)
    if handled is not None:
        lines.append(f"Handled by the application: {'yes' if handled else 'no'}")
    level = event_properties.get("$exception_level")
    if isinstance(level, str) and level:
        lines.append(f"Level: {level}")
    page = _page_without_query(event_properties.get("$current_url"))
    if page:
        lines.append(f"Page: {page}")
    library = event_properties.get("$lib")
    if isinstance(library, str) and library:
        lines.append(f"SDK: {library}")
    return "\n".join(lines)


def _mechanism_handled(event_properties: dict[str, object]) -> bool | None:
    # Same source as cymbal's severity heuristic: the first exception's mechanism, not `$exception_handled`.
    exception_list = event_properties.get("$exception_list")
    if not isinstance(exception_list, list) or not exception_list or not isinstance(exception_list[0], dict):
        return None
    mechanism = exception_list[0].get("mechanism")
    handled = mechanism.get("handled") if isinstance(mechanism, dict) else None
    return handled if isinstance(handled, bool) else None


def _page_without_query(current_url: object) -> str | None:
    # Query strings and fragments can carry tokens or personal data, and the path already names the feature.
    if not isinstance(current_url, str) or not current_url:
        return None
    parsed = urlparse(current_url)
    if not parsed.netloc:
        return None
    return f"{parsed.netloc}{parsed.path}"


def infer_severity(team_id: int, state: str) -> ChoiceAnswer | None:
    """Ask the decision model for a severity. Raises the ml_inference gateway errors unchanged."""
    result = ml_inference.decide(
        DecisionRequest(
            team_id=team_id,
            state=state,
            questions={_SEVERITY_QUESTION_ID: _SEVERITY_QUESTION},
            model=SEVERITY_INFERENCE_MODEL,
        )
    )
    answer = result.answers.get(_SEVERITY_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in ErrorTrackingIssue.Severity.values:
        logger.warning("error_tracking_severity_inference_unexpected_answer", team_id=team_id, answer=repr(answer))
        return None
    return answer


@frozen
class InferredSeverityWrite:
    inferred_severity: str
    stored_severity: str | None

    @property
    def applied(self) -> bool:
        return self.stored_severity == self.inferred_severity


def apply_inferred_severity(
    team_id: int, issue_id: UUID | str, *, expected: str | None, inferred: str
) -> InferredSeverityWrite:
    """Set a model-inferred severity unless the severity changed after ingestion set `expected`."""
    if expected != inferred:
        with transaction.atomic():
            # The conditional update keeps a severity that a person or a rule set while the model ran.
            updated = ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id, severity=expected).update(
                severity=inferred, state_updated_at=timezone.now()
            )
            if updated:
                _log_inferred_severity(team_id, issue_id, expected=expected, inferred=inferred)

    write = InferredSeverityWrite(
        inferred_severity=inferred,
        stored_severity=ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id)
        .values_list("severity", flat=True)
        .first(),
    )
    if write.applied:
        # Sync even when this call wrote nothing: a retry after a failed sync finds the severity
        # already stored, and the sync is idempotent.
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=team_id)
    return write


def _log_inferred_severity(team_id: int, issue_id: UUID | str, *, expected: str | None, inferred: str) -> None:
    issue = ErrorTrackingIssue.objects.select_related("team").get(team_id=team_id, id=issue_id)
    log_activity(
        organization_id=issue.team.organization_id,
        team_id=team_id,
        user=None,
        was_impersonated=False,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="updated",
        detail=Detail(
            name=issue.name,
            changes=[
                Change(type="ErrorTrackingIssue", field="severity", before=expected, after=inferred, action="changed")
            ],
        ),
    )
