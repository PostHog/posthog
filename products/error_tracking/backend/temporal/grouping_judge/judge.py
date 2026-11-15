"""The LLM judge. It sees two document texts and nothing about how they were paired."""

from anthropic import Anthropic, AnthropicError, APIConnectionError, APIStatusError, APITimeoutError
from anthropic.types import ToolChoiceToolParam, ToolParam

from posthog.dataclasses import frozen

from products.error_tracking.backend.temporal.grouping_judge.types import JudgeOutcome

JUDGE_MODEL = "claude-haiku-4-5"
# Room for the reasoning, which comes before the verdict.
MAX_TOKENS = 768
# Pins the call to Bedrock in the caller's region, so EU documents never leave EU Bedrock.
PROVIDER_HEADERS = {"X-PostHog-Provider": "bedrock"}

SYSTEM_PROMPT = """\
You are an expert in error tracking and crash triage. You will be shown two error documents, each rendered \
as an error type + message followed by a stack trace. They come from the same application but were assigned \
different grouping fingerprints.

Decide whether they represent the SAME underlying issue — i.e. a developer fixing one would consider the \
other a duplicate that should be grouped with it, because one fix resolves both.

How to decide:
1. Find the THROW SITE of each document: the error type, the message, and the application frames nearest to \
where the error was raised. Frames are usually listed from the outermost caller first to the throw site last \
(numbered frames: #00 is the throw site).
2. If the throw sites match, the documents are the SAME issue even when they differ in:
- dynamic values anywhere: IDs, URLs and URL path segments, numbers, percentages, timestamps, memory \
addresses, thread/process names, session ids, user input, in any language;
- line/column numbers, build hashes in file names, bundler module ids and chunk names, and minified frame \
names (1–3 character identifiers such as a, Qx, b7 that change between builds);
- the outer callers above the throw site, extra or missing frames at the bottom of the stack, stacks \
truncated at a different depth (e.g. stack overflows), and frames inside framework or runtime internals \
(React reconciler/scheduler, webpack runtime, unsymbolicated VM addresses);
- a frame whose "file" is a page URL (/pricing vs /blog): it is the same inline, injected or single-page-app \
script running on another page; compare its function names instead. When those frames have no function \
names, they count as the same script only if the message is identical and the frame shape matches; inline \
event handlers (onclick, ...) belong to their own page and are not shared;
- the variable part of a templated message when the error type, template and throw site match: the requested \
path or asset in not-found / failed-to-load errors (404 for /a vs /b, a failed-to-load error for different \
assets), or a list of rejected fields from the same validator. When the variable part is itself an error \
message, compare that inner error as its own throw site;
- which chunk or module failed in chunk / dynamic-import load failures (ChunkLoadError, "error loading \
dynamically imported module"): one issue (deploy skew or network);
- which caller hit the same failing dependency in transient transport-level failures (no HTTP response: \
network error, aborted request, timeout, DNS or TLS failure, connection pool exhausted, or HTTP \
502/503/504): group by the failure, not by the caller. An HTTP 4xx or 500 response is never transient;
- which hook or component hit a null React dispatcher ("reading 'useState'", 'useContext', ... thrown inside \
React's hook exports): one issue (duplicate React copy or hook called outside render);
- the page on which a browser- or extension-injected script failed (window.ethereum, __firefox__, \
_AutofillCallbackHandler).
3. They are DIFFERENT issues when the throw sites differ:
- different meaningful application files, components, handlers or functions nearest the throw site (when the \
error is raised inside framework or library code, the first application frames calling into it decide) \
(CartSummary.tsx vs OrderHistory.tsx, component Checkout vs Profile), even with an identical message: the \
same failure in two places needs two fixes. Named frames without a file (App, loadSettings) are application \
frames, not minified names;
- with no application frames at all, the library frame that calls into the framework stands in for the \
application frame (a websocket library vs a state library, each calling into react-dom);
- names that come from the application's own code differ: the undefined identifier (googletag vs jQuery is \
not defined), the missing property, key or module, a nested error class in the message (NetworkError vs \
AbortError), a different HTTP status (404 vs 401, 500 vs 503) or an HTTP status vs a network error, or a \
different operation;
- React minified errors (e.g. #418) with a different error code, OR different args (text vs HTML), OR \
different route-specific files or components (settings-*.js vs billing-*.js): any one of these makes them \
different;
- the error type or root message differs in meaning, not just in dynamic values.

Examples (SAME): "Page not found: /old-page" vs "Page not found: /docs/missing" with the same stack; "Failed \
to load asset: /assets/icons/close.svg" vs "/assets/logo.svg"; the same recursion frames on /pricing vs \
/blog; a connection-pool-exhausted error reached from two different request handlers; a validation error \
listing different rejected fields from the same validator.
Examples (DIFFERENT): "googletag is not defined" vs "jQuery is not defined"; "status code 404" vs "Network \
Error"; the same TypeError thrown in component Checkout vs component Profile.

Before deciding, name the throw site of each document. Then check the DIFFERENT rules in step 3 first: if \
any one applies, answer DIFFERENT. Only otherwise check the SAME rules in step 2: if they explain every \
difference, answer SAME. Product decisions in step 2 (e.g. different missing assets or 404 paths are one \
issue) override the intuition that each needs its own fix."""

USER_PROMPT_TEMPLATE = """Do these two error documents represent the same underlying issue?

<document_a>
{a}
</document_a>

<document_b>
{b}
</document_b>"""

VERDICT_TOOL_NAME = "record_verdict"
VERDICT_TOOL: ToolParam = {
    "name": VERDICT_TOOL_NAME,
    "description": "Record whether the two error documents are the same underlying issue.",
    "input_schema": {
        "type": "object",
        # Reasoning first, so the model names each throw site before it commits to a verdict.
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "Throw site of each document, which rule decides, in two or three short sentences",
            },
            "same_issue": {
                "type": "boolean",
                "description": "True if both documents represent the same underlying issue",
            },
        },
        "required": ["reasoning", "same_issue"],
    },
}

VERDICT_TOOL_CHOICE: ToolChoiceToolParam = {"type": "tool", "name": VERDICT_TOOL_NAME}


@frozen
class JudgeVerdict:
    outcome: JudgeOutcome
    same_issue: bool | None = None


def _outcome_for_status(status_code: int) -> JudgeOutcome:
    if status_code >= 500 or status_code == 429:
        return "unavailable"
    return "rejected"


def judge_pair(client: Anthropic, *, document_a: str, document_b: str, timeout_seconds: float) -> JudgeVerdict:
    try:
        # SDK retries are off so each call stays inside the caller's time budget.
        response = client.with_options(max_retries=0, timeout=timeout_seconds).messages.create(
            model=JUDGE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(a=document_a, b=document_b)}],
            tools=[VERDICT_TOOL],
            tool_choice=VERDICT_TOOL_CHOICE,
            extra_headers=PROVIDER_HEADERS,
        )
    except APITimeoutError:
        return JudgeVerdict(outcome="timeout")
    except APIStatusError as error:
        return JudgeVerdict(outcome=_outcome_for_status(error.status_code))
    except APIConnectionError:
        return JudgeVerdict(outcome="unavailable")
    except AnthropicError:
        return JudgeVerdict(outcome="invalid")

    for block in response.content:
        if block.type != "tool_use" or block.name != VERDICT_TOOL_NAME:
            continue
        verdict = block.input if isinstance(block.input, dict) else {}
        same_issue = verdict.get("same_issue")
        if isinstance(same_issue, bool):
            return JudgeVerdict(outcome="judged", same_issue=same_issue)
    return JudgeVerdict(outcome="invalid")
