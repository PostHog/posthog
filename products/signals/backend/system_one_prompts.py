import json
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import structlog
import posthoganalytics
from posthoganalytics.ai.prompts import PromptResult, Prompts

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60
DEFAULT_SYSTEM_ONE_MODEL = "posthog/hogference/jevk5-fp8-0.2"
ALLOWED_SYSTEM_ONE_MODELS = {DEFAULT_SYSTEM_ONE_MODEL, "posthog/hogference/jeeves-0.1"}
SAFETY_RESPONSE_FIELDS = {
    "signals-signal-safety-system-one": ("safe", "threat_type", "explanation"),
    "signals-report-safety-system-one": ("choice", "explanation"),
}
SAFETY_REDACTION_INSTRUCTION = (
    "Never reproduce a credential, token, key, cookie, or other secret value in the explanation"
)


@frozen
class SystemOnePrompt:
    name: str
    policy: str
    question: str
    model: str
    threshold: float
    version: int | None
    source: Literal["managed", "bundled"]


def bundled_prompt(name: str, policy: str, question: str, threshold: float) -> SystemOnePrompt:
    return SystemOnePrompt(
        name=name,
        policy=policy,
        question=question,
        model=DEFAULT_SYSTEM_ONE_MODEL,
        threshold=threshold,
        version=None,
        source="bundled",
    )


def _valid_actionability_policy(policy: str) -> bool:
    if "{description}" not in policy:
        return False
    # apply_steering finds these markers only at the start of a line, so a marker elsewhere cannot anchor steering.
    lines = policy.split("\n")
    if not any(line.startswith("When in doubt, classify as ACTIONABLE") for line in lines):
        return False
    if not any(line.startswith("Respond with exactly one word") for line in lines):
        return False
    try:
        policy.format(description="record")
    except (KeyError, ValueError, IndexError):
        return False
    return True


def _parse_prompt(result: PromptResult, fallback: SystemOnePrompt) -> SystemOnePrompt | None:
    if result.source == "code_fallback":
        return None
    policy = result.prompt
    config = result.config
    if not isinstance(policy, str) or not policy.strip() or not isinstance(config, dict):
        return None
    model = config.get("model")
    question = config.get("question")
    threshold = config.get("threshold")
    if not isinstance(model, str) or model not in ALLOWED_SYSTEM_ONE_MODELS:
        return None
    if not isinstance(question, str) or not question.strip():
        return None
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        return None
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        return None
    if fallback.name.startswith("signals-actionability-") and not _valid_actionability_policy(policy):
        return None
    response_fields = SAFETY_RESPONSE_FIELDS.get(fallback.name)
    if response_fields is not None and (
        "json" not in policy.lower()
        or any(f'"{field}"' not in policy for field in response_fields)
        or SAFETY_REDACTION_INSTRUCTION not in policy
    ):
        return None
    if fallback.name == "signals-report-safety-system-one" and len(
        json.dumps(policy, ensure_ascii=False).encode()
    ) > len(json.dumps(fallback.policy, ensure_ascii=False).encode()):
        return None
    if not isinstance(result.version, int) or result.version < 1:
        return None
    return SystemOnePrompt(
        name=fallback.name,
        policy=policy,
        question=question,
        model=model,
        threshold=float(threshold),
        version=result.version,
        source="managed",
    )


def fetch_prompt(fallback: SystemOnePrompt, *, version: int | None = None) -> SystemOnePrompt | None:
    if not posthoganalytics.personal_api_key:
        return None
    result = Prompts(posthoganalytics, capture_errors=True).get(
        fallback.name,
        with_metadata=True,
        label=PROMPT_LABEL if version is None else None,
        version=version,
        fallback=fallback.policy,
    )
    prompt = _parse_prompt(result, fallback)
    if prompt is None:
        logger.warning("Invalid Signals System One prompt", prompt_name=fallback.name, prompt_version=result.version)
    return prompt


class _PromptState:
    def __init__(self, prompt: SystemOnePrompt) -> None:
        self.prompt = prompt
        self.refreshed_at = float("-inf")
        self.refreshing = False


class _PromptCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="signals-system-one-prompt")
        self._states: dict[str, _PromptState] = {}

    def current(self, fallback: SystemOnePrompt) -> SystemOnePrompt:
        with self._lock:
            state = self._states.setdefault(fallback.name, _PromptState(fallback))
            if not state.refreshing and time.monotonic() - state.refreshed_at >= PROMPT_REFRESH_SECONDS:
                state.refreshing = True
                self._executor.submit(self._refresh, fallback)
            return state.prompt

    def _refresh(self, fallback: SystemOnePrompt) -> None:
        try:
            prompt = fetch_prompt(fallback)
        except Exception:
            logger.exception("Signals System One prompt refresh failed", prompt_name=fallback.name)
            prompt = None
        with self._lock:
            state = self._states[fallback.name]
            if prompt is None and state.prompt.source == "managed":
                logger.warning("Signals System One prompt reverted to bundled", prompt_name=fallback.name)
            state.prompt = prompt or fallback
            state.refreshed_at = time.monotonic()
            state.refreshing = False


_CACHE = _PromptCache()


def current_prompt(fallback: SystemOnePrompt) -> SystemOnePrompt:
    return _CACHE.current(fallback)
