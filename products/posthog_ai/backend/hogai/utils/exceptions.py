import httpx
import openai
import anthropic
from prometheus_client import Counter

# All LLM API exceptions (for catching)
LLM_API_EXCEPTIONS = (anthropic.APIError, openai.APIError)

# Transient errors that may resolve on retry (5xx, rate limits, timeouts, connection issues)
LLM_TRANSIENT_EXCEPTIONS = (
    # Anthropic transient errors
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    # OpenAI transient errors
    openai.InternalServerError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)

# httpx transport errors that can escape SDK wrapping during streaming.
# These are network-level issues (not LLM provider errors) and are tracked
# on a separate counter to avoid false "LLM Provider Errors" alerts.
HTTPX_TRANSPORT_EXCEPTIONS = (httpx.ReadError, httpx.ConnectError)

# Client/validation errors that won't resolve on retry (400, 422, etc.)
LLM_CLIENT_EXCEPTIONS = (
    # Anthropic client errors
    anthropic.BadRequestError,
    anthropic.UnprocessableEntityError,
    # OpenAI client errors
    openai.BadRequestError,
    openai.UnprocessableEntityError,
)

LLM_PROVIDER_ERROR_COUNTER = Counter(
    "posthog_ai_llm_provider_errors_total",
    "Total number of LLM provider API errors (transient)",
    ["provider"],
)

LLM_CLIENT_ERROR_COUNTER = Counter(
    "posthog_ai_llm_client_errors_total",
    "Total number of LLM client/validation errors",
    ["provider"],
)

LLM_TRANSPORT_ERROR_COUNTER = Counter(
    "posthog_ai_llm_transport_errors_total",
    "Total number of httpx transport errors during LLM streaming",
    ["error_type"],
)

# Unexpected exceptions that crash an agent run (e.g. a code bug or a stale import),
# as opposed to the known LLM provider/client/transport errors counted above. These
# bubble to the catch-all in the runner and return a FailureMessage to the user — an
# agent generation that never finished. Sits at ~0 in steady state, so a sustained
# rate signals that a recent change broke an agent path in production.
AGENT_RUN_UNHANDLED_ERROR_COUNTER = Counter(
    "posthog_ai_agent_run_unhandled_errors_total",
    "Total number of agent runs that failed with an unexpected (non-LLM) exception",
    ["error_type"],
)


def resolve_llm_provider(exc: Exception) -> str:
    """Extract the LLM provider name from an exception.

    Only meaningful for SDK exceptions (anthropic.*, openai.*).
    """
    return type(exc).__module__.partition(".")[0] or "unknown_provider"


class GenerationCanceled(Exception):
    """Raised when generation is canceled."""

    pass
