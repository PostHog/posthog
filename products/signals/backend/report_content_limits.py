"""The embeddability cap on report content (title + summary).

A report's title + summary feed the embedding pipeline (the report's backing signals — scout
reports, plan reports), and the text-embedding-3 family rejects inputs over 8191 tokens. Every
report must stay embeddable, so report content is capped at MAX_EMBEDDABLE_REPORT_TOKENS = 8000
tokens combined (headroom for the separator the emit paths add):

- `SignalReport.save()` enforces the cap unconditionally, truncating the summary (with a warning)
  when a write would exceed it — the backstop that keeps pipeline/LLM writers from ever persisting
  an unembeddable report.
- Interactive write paths (the report edit API, the scout emit/edit tools) validate up front via
  `summary_embedding_error` so agents get a clear 400 instead of a silent truncation.

Char caps alone (10k on the edit API, 20k on the scout channel) don't protect here: token-dense
content (CJK, emoji) blows past 8191 tokens well inside those limits.

The tiktoken encoder comes from `posthog.helpers.tiktoken_encoding`, which caches it process-wide
(`functools.cache`) — encoder construction is expensive and must never happen per call.
"""

import logging

from posthog.helpers.tiktoken_encoding import TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model

logger = logging.getLogger(__name__)

# Combined cap for title + summary. Mirrors MAX_SIGNAL_DESCRIPTION_TOKENS on the signal channel.
MAX_EMBEDDABLE_REPORT_TOKENS = 8000


def embedding_token_count(text: str) -> int:
    return len(get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL).encode(text))


def summary_embedding_error(summary: str) -> str | None:
    """Error message when a summary alone would blow the report's embeddability cap, else None.

    The up-front check for interactive writers. Title tokens aren't known at every call site; the
    title is char-capped small enough that `SignalReport.save()`'s combined-cap backstop covers the
    residual edge.
    """
    tokens = embedding_token_count(summary)
    if tokens > MAX_EMBEDDABLE_REPORT_TOKENS:
        return (
            f"Summary is too long to embed: {tokens} tokens (max {MAX_EMBEDDABLE_REPORT_TOKENS} for the "
            "report's title + summary). Tighten it — the summary is a quick current-status view; detail "
            "belongs in the artefact log."
        )
    return None


def truncate_summary_to_embeddable(title: str | None, summary: str, *, report_id: str | None = None) -> str:
    """Truncate `summary` so title + summary fit MAX_EMBEDDABLE_REPORT_TOKENS, logging a warning.

    Token-sliced (encode → cut → decode), so the result is exact regardless of content density.
    Returns `summary` unchanged when already within the cap.
    """
    encoding = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
    title_tokens = len(encoding.encode(title)) if title else 0
    summary_tokens = encoding.encode(summary)
    budget = MAX_EMBEDDABLE_REPORT_TOKENS - title_tokens
    if len(summary_tokens) <= budget:
        return summary
    logger.warning(
        "signals.report_content.truncated_to_embeddable",
        extra={
            "report_id": report_id,
            "title_tokens": title_tokens,
            "summary_tokens": len(summary_tokens),
            "budget": budget,
        },
    )
    return encoding.decode(summary_tokens[: max(budget, 0)])
