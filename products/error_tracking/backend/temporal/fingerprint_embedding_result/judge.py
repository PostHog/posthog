"""LLM judge for auto-merging fingerprints whose nearest neighbour is too far for a distance-only merge.

The rule: merge automatically when the embedding distance is below `auto_merge_threshold`; between
that and `judge_max_distance`, ask the configured decision model on the PostHog AI gateway whether
the two error documents are the same issue and merge when its probability reaches `judge_cutoff`.

Every knob comes from the `error-tracking-auto-merge-config` feature flag payload, evaluated per
team, so thresholds can change without a deploy. With no payload the behaviour is today's
distance-only rule. `judge_shadow` scores and reports without merging, to evaluate settings on
live traffic first.

The prompt version is recorded on every judged and merged event, so a prompt change can be
compared against the previous one on live traffic.
"""

import time
import random
import dataclasses
from typing import Literal

import structlog
import posthoganalytics

from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import build_system_one_client
from posthog.models import Team

logger = structlog.get_logger(__name__)

AUTO_MERGE_CONFIG_FLAG = "error-tracking-auto-merge-config"
DEFAULT_AUTO_MERGE_THRESHOLD = 0.019
# Only approved gateway models may receive error documents; each needs its own calibrated cutoff.
type JudgeModel = Literal["posthog/hogference/jevk5-fp8-0.2", "posthog/hogference/jeeves-0.1"]
JEEVES_MODEL: JudgeModel = "posthog/hogference/jeeves-0.1"
JEVK5_MODEL: JudgeModel = "posthog/hogference/jevk5-fp8-0.2"
JUDGE_MODEL: JudgeModel = JEEVES_MODEL
JUDGE_PROMPT_VERSION = "v5"
JUDGE_QUESTION_KEY = "same_issue"
MAX_DOCUMENT_CHARS = 6000  # what the judge was evaluated with
# Rate limits and overload clear within seconds; retries stay inside the judge timeout.
RETRYABLE_STATUS_CODES = frozenset({429, 529})
RETRY_BACKOFF_SECONDS = (0.25, 0.5, 1.0)
MIN_ATTEMPT_SECONDS = 1.0


@dataclasses.dataclass(frozen=True)
class AutoMergeConfig:
    # Merge without the judge when the nearest-neighbour distance is strictly below this.
    auto_merge_threshold: float = DEFAULT_AUTO_MERGE_THRESHOLD
    judge_enabled: bool = False
    judge_model: JudgeModel = JUDGE_MODEL
    # Ask the judge for distances in [auto_merge_threshold, judge_max_distance].
    judge_max_distance: float = 0.1
    # Merge when the judge's P(same issue) is at least this.
    judge_cutoff: float = 0.9
    # Score and report, but never merge on the judge's verdict.
    judge_shadow: bool = True
    judge_timeout_seconds: float = 10.0


# Today's distance-only rule: what every team gets without a flag payload.
DEFAULT_AUTO_MERGE_CONFIG = AutoMergeConfig()


def _bounded(value: object, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        return default
    return float(value)


def _judge_model(value: object) -> JudgeModel | None:
    if value == JEEVES_MODEL:
        return JEEVES_MODEL
    if value == JEVK5_MODEL:
        return JEVK5_MODEL
    return None


def parse_auto_merge_config(payload: object) -> AutoMergeConfig:
    """Build the config from a flag payload, keeping the default for any missing or invalid field."""
    payload = payload if isinstance(payload, dict) else {}
    raw_judge = payload.get("judge")
    judge: dict[str, object] = raw_judge if isinstance(raw_judge, dict) else {}
    defaults = AutoMergeConfig()
    judge_model = _judge_model(judge.get("model", JUDGE_MODEL))
    raw_cutoff = judge.get("cutoff")
    judge_cutoff = _bounded(raw_cutoff, defaults.judge_cutoff, 0, 1)
    explicit_cutoff_valid = _bounded(raw_cutoff, -1, 0, 1) != -1
    config = AutoMergeConfig(
        auto_merge_threshold=_bounded(payload.get("auto_merge_threshold"), defaults.auto_merge_threshold, 0, 1),
        judge_enabled=judge.get("enabled") is True
        and judge_model is not None
        and ("model" not in judge or explicit_cutoff_valid),
        judge_model=judge_model or JUDGE_MODEL,
        judge_max_distance=_bounded(judge.get("max_distance"), defaults.judge_max_distance, 0, 1),
        judge_cutoff=judge_cutoff,
        judge_shadow=judge.get("shadow") is not False,
        judge_timeout_seconds=_bounded(judge.get("timeout_seconds"), defaults.judge_timeout_seconds, 0.1, 60),
    )
    if config.judge_max_distance < config.auto_merge_threshold:
        # An inverted band would judge nothing; make the misconfiguration visible instead of silent.
        logger.warning("error_tracking_auto_merge_config_inverted_band", payload=payload)
        return dataclasses.replace(config, judge_enabled=False)
    return config


def load_auto_merge_config(team: Team) -> AutoMergeConfig:
    """Read the per-team config from the feature flag payload; fall back to today's rule on any failure."""
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            AUTO_MERGE_CONFIG_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}},
            # The hot path runs for every new fingerprint: never block on a remote /flags call.
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as err:
        logger.warning("error_tracking_auto_merge_config_unavailable", team_id=team.id, error=str(err))
        return AutoMergeConfig()
    return parse_auto_merge_config(payload)


# Shared same-issue rubric. It encodes the grouping decisions: not-found paths and assets are one
# issue, chunk-load failures are one issue, transient transport failures group by the failure,
# React minified errors split on code/args/route, injected scripts group across pages.
JUDGE_QUESTION = """\
Do these two error documents represent the SAME underlying issue, i.e. would a developer fixing one \
consider the other a duplicate that should be grouped with it, because one fix resolves both?
How to decide:
1. Find the THROW SITE of each document: the error type, the message, and the application frames \
nearest to where the error was raised. Frames are usually listed from the outermost caller first to \
the throw site last (numbered frames: #00 is the throw site).
2. If the throw sites match, the documents are the SAME issue even when they differ in:
- dynamic values anywhere: IDs, URLs and URL path segments, numbers, percentages, timestamps, memory \
addresses, thread/process names, session ids, user input, in any language;
- line/column numbers, build hashes in file names, bundler module ids and chunk names, and minified \
frame names (1–3 character identifiers such as iu, o6, fT that change between builds);
- the outer callers above the throw site, extra or missing frames at the bottom of the stack, stacks \
truncated at a different depth (e.g. stack overflows), and frames inside framework or runtime \
internals (React reconciler/scheduler, webpack runtime, unsymbolicated VM addresses);
- a frame whose "file" is a page URL (/products vs /blog): it is the same inline, injected or \
single-page-app script running on another page; compare its function names instead. When those \
frames have no function names, they count as the same script only if the message is identical and \
the frame shape matches; inline event handlers (onclick, ...) belong to their own page and are not shared;
- the variable part of a templated message when the error type, template and throw site match: the \
requested path or asset in not-found / failed-to-load errors (404 for /a vs /b, failed-to-load \
errors for different textures or images), or a list of rejected fields from the same validator. When \
the variable part is itself an error message, compare that inner error as its own throw site;
- which chunk or module failed in chunk / dynamic-import load failures (ChunkLoadError, "error loading \
dynamically imported module"): one issue (deploy skew or network);
- which caller hit the same failing dependency in transient transport-level failures (no HTTP \
response: network error, aborted request, timeout, DNS or TLS failure, connection pool exhausted, or \
HTTP 502/503/504): group by the failure, not by the caller. An HTTP 4xx or 500 response is never transient;
- which hook or component hit a null React dispatcher ("reading 'useState'", 'useContext', ... thrown \
inside React's hook exports): one issue (duplicate React copy or hook called outside render);
- the page on which a browser- or extension-injected script failed (window.ethereum, __firefox__, \
_AutofillCallbackHandler).
3. They are DIFFERENT issues when the throw sites differ:
- different meaningful application files, components, handlers or functions nearest the throw site \
(when the error is raised inside framework or library code, the first application frames calling into \
it decide), e.g. OrderSummary.tsx vs OrderHistory.tsx, component Pricing vs Checkout, even with an \
identical message: the same failure in two places needs two fixes. Named frames without a file \
(Pricing, loadPricingPlans) are application frames, not minified names;
- with no application frames at all, the library frame that calls into the framework stands in for \
the application frame (swr vs zustand calling into react-dom);
- names that come from the application's own code differ: the undefined identifier (googletag vs \
jQuery is not defined), the missing property, key or module, a nested error class in the message \
(NetworkError vs AbortError), a different HTTP status (404 vs 401, 500 vs 503) or an HTTP status vs a \
network error, or a different operation;
- React minified errors (e.g. #418) with a different error code, OR different args (text vs HTML), OR \
different route-specific files or components (settings-*.js vs profile-*.js): any one of these makes \
them different;
- the error type or root message differs in meaning, not just in dynamic values.

Examples (SAME): "Page not found: /config.js" vs "Page not found: /wp-json/x" with the same stack; \
"Failed to load texture: hero.png" vs "Failed to load texture: icons/logo.png"; the same recursion \
frames on /products vs /blog; a connection-pool-exhausted error reached from two different request handlers; a \
validation error listing different rejected fields from the same validator.
Examples (DIFFERENT): "googletag is not defined" vs "jQuery is not defined"; "status code 404" vs \
"Network Error"; the same TypeError thrown in component Pricing vs component Checkout.

Before deciding, name the throw site of each document. Then check the DIFFERENT rules in step 3 \
first: if any one applies, answer DIFFERENT. Only otherwise check the SAME rules in step 2: if they \
explain every difference, answer SAME. Product decisions in step 2 (e.g. different missing assets or \
404 paths are one issue) override the intuition that each needs its own fix."""


TRUNCATION_MARKER = "\n[... frames omitted ...]\n"


def _truncate(document: str) -> str:
    """Keep the message (start) and the throw site (end): frames run outermost first, so the end matters."""
    if len(document) <= MAX_DOCUMENT_CHARS:
        return document
    head = MAX_DOCUMENT_CHARS // 4
    tail = MAX_DOCUMENT_CHARS - head - len(TRUNCATION_MARKER)
    return document[:head] + TRUNCATION_MARKER + document[-tail:]


def judge_state(document: str, candidate_document: str) -> str:
    return (
        "Two error documents from the same application were assigned different grouping "
        "fingerprints. Each is an error type + message followed by a stack trace.\n\n"
        f"<document_a>\n{_truncate(document)}\n</document_a>\n\n"
        f"<document_b>\n{_truncate(candidate_document)}\n</document_b>"
    )


class JudgeUnavailableError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class JudgeVerdict:
    score: float
    latency_ms: float


def ask_judge(
    team_id: int, document: str, candidate_document: str, timeout_seconds: float, *, model: JudgeModel = JUDGE_MODEL
) -> JudgeVerdict:
    """Ask the judge model for P(same issue). Raises JudgeUnavailableError when it can't answer."""
    start = time.monotonic()
    remaining_seconds = timeout_seconds
    for backoff in (*RETRY_BACKOFF_SECONDS, None):
        try:
            client = build_system_one_client(
                model=model, ai_product="error_tracking", team_id=team_id, timeout=remaining_seconds
            )
            result = client.decide(
                state=judge_state(document, candidate_document),
                questions={JUDGE_QUESTION_KEY: NoulQuestion(instructions=JUDGE_QUESTION)},
            )
            break
        except SystemOneNotConfigured as err:
            raise JudgeUnavailableError(str(err)) from err
        except SystemOneRequestFailed as err:
            if backoff is None or err.status_code not in RETRYABLE_STATUS_CODES:
                raise JudgeUnavailableError(str(err)) from err
            # Jitter spreads the retries of workers that were throttled together.
            delay = backoff * random.uniform(1, 2)
            remaining_seconds = timeout_seconds - (time.monotonic() - start) - delay
            if remaining_seconds < MIN_ATTEMPT_SECONDS:
                raise JudgeUnavailableError(str(err)) from err
            time.sleep(delay)
    answer = result.answers.get(JUDGE_QUESTION_KEY)
    if not isinstance(answer, NoulAnswer):
        raise JudgeUnavailableError("Judge refused or gave no answer")
    return JudgeVerdict(score=answer.probability, latency_ms=(time.monotonic() - start) * 1000)
