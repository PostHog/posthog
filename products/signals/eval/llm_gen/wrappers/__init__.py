"""Per-source wrappers that turn canonical LLM-generated signals into source-specific raw fixture records.

Each wrapper produces a dict that the matching emitter (github_issue_emitter,
linear_issue_emitter, zendesk_ticket_emitter, conversations_ticket_emitter)
will accept unchanged, so the LLM-gen path reuses the same parsers as the
fixture-emit path.
"""

from collections.abc import Callable
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.conversations import wrap_as_conversations_ticket
from products.signals.eval.llm_gen.wrappers.github import wrap_as_github_issue
from products.signals.eval.llm_gen.wrappers.linear import wrap_as_linear_issue
from products.signals.eval.llm_gen.wrappers.zendesk import wrap_as_zendesk_ticket

# Maps the CLI --type arg to (registry source_type, registry schema_name, wrapper fn).
# Source/schema names match emit_signals_from_fixture._SOURCES.
WrapperFn = Callable[[CanonicalSignal, int, int], dict[str, Any]]

WRAPPERS: dict[str, tuple[str, str, WrapperFn]] = {
    "github": ("Github", "issues", wrap_as_github_issue),
    "linear": ("Linear", "issues", wrap_as_linear_issue),
    "zendesk": ("Zendesk", "tickets", wrap_as_zendesk_ticket),
    "conversations": ("conversations", "tickets", wrap_as_conversations_ticket),
}

SOURCE_KINDS = tuple(WRAPPERS.keys())

__all__ = [
    "WRAPPERS",
    "SOURCE_KINDS",
    "WrapperFn",
    "wrap_as_github_issue",
    "wrap_as_linear_issue",
    "wrap_as_zendesk_ticket",
    "wrap_as_conversations_ticket",
]
