from parameterized import parameterized
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError as TemporalTimeoutError,
    TimeoutType,
)

from posthog.models.github_integration_base import GitHubIntegrationError

from products.signals.backend.temporal.failure_classification import (
    FAILURE_REASON_GITHUB_INTEGRATION,
    FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT,
    FAILURE_REASON_SANDBOX_AGENT_TIMEOUT,
    FAILURE_REASON_UNKNOWN,
    classify_failure_reason,
)


def _activity_error(cause: BaseException) -> ActivityError:
    """Wrap a cause the way Temporal does when an activity fails and reaches the workflow."""
    err = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="run_agentic_report_activity",
        activity_id="1",
        retry_state=None,
    )
    err.__cause__ = cause
    return err


def _app_error(message: str, type: str) -> ApplicationError:
    return ApplicationError(message, type=type)


class TestClassifyFailureReason:
    @parameterized.expand(
        [
            # GitHub App auth failures — raw exception inside the activity.
            (
                "github_raw_401",
                GitHubIntegrationError("unauthorized", status_code=401),
                FAILURE_REASON_GITHUB_INTEGRATION,
            ),
            ("github_raw_404", GitHubIntegrationError("gone", status_code=404), FAILURE_REASON_GITHUB_INTEGRATION),
            # A non-auth GitHub status is not the permanent-auth bucket.
            ("github_raw_500", GitHubIntegrationError("server error", status_code=500), FAILURE_REASON_UNKNOWN),
            # ...and the ApplicationError select_repository re-raises it as, seen from the workflow.
            (
                "github_wrapped",
                _activity_error(_app_error("installation suspended", "GitHubIntegrationError")),
                FAILURE_REASON_GITHUB_INTEGRATION,
            ),
            # LLM rate limits / timeouts surfaced through the activity boundary as text.
            (
                "llm_rate_limit_wrapped",
                _activity_error(_app_error("rate_limit: 429 Too Many Requests", "RuntimeError")),
                FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT,
            ),
            (
                "llm_overloaded_raw",
                RuntimeError("Anthropic overloaded_error, please retry"),
                FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT,
            ),
            # An LLM rate limit reaching us via the sandbox terminal-status path is still an LLM cause.
            (
                "llm_via_sandbox_terminal",
                _activity_error(
                    _app_error(
                        "custom_prompt - drain_final_log: TaskRun reached terminal status=FAILED "
                        "(cause: rate_limit: 429)",
                        "RuntimeError",
                    )
                ),
                FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT,
            ),
            # Sandbox agent went silent — poll budget exhausted / no message drained.
            (
                "sandbox_poll_timeout_wrapped",
                _activity_error(_app_error("custom_prompt - poll_for_turn: timed out after 1800s", "RuntimeError")),
                FAILURE_REASON_SANDBOX_AGENT_TIMEOUT,
            ),
            (
                "sandbox_no_message_wrapped",
                _activity_error(
                    _app_error(
                        "custom_prompt - drain_final_log: TaskRun reached terminal status=FAILED — no agent message",
                        "RuntimeError",
                    )
                ),
                FAILURE_REASON_SANDBOX_AGENT_TIMEOUT,
            ),
            (
                "sandbox_poll_timeout_raw",
                RuntimeError("poll_for_turn: timed out after 1800s"),
                FAILURE_REASON_SANDBOX_AGENT_TIMEOUT,
            ),
            # Temporal-level activity timeout (start_to_close / heartbeat) — no ApplicationError message.
            (
                "sandbox_temporal_timeout",
                _activity_error(
                    TemporalTimeoutError("activity timeout", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[])
                ),
                FAILURE_REASON_SANDBOX_AGENT_TIMEOUT,
            ),
            # Anything unmapped stays in the historical catch-all bucket.
            (
                "unknown_wrapped",
                _activity_error(_app_error("something totally unexpected", "ValueError")),
                FAILURE_REASON_UNKNOWN,
            ),
            ("unknown_raw", ValueError("nothing matched here"), FAILURE_REASON_UNKNOWN),
        ]
    )
    def test_classify(self, _name: str, exc: BaseException, expected: str) -> None:
        assert classify_failure_reason(exc) == expected
