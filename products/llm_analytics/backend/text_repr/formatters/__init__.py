"""
Text representation formatters for LLM Analytics events.

Pure Python implementation for formatting $ai_generation, $ai_span, and $ai_trace events
into human-readable text representations.

Main entry points:
- format_event_text_repr: Format single events ($ai_generation, $ai_span)
- format_trace_text_repr: Format full traces with hierarchy
- llm_trace_to_formatter_format: Convert LLMTrace to format_trace_text_repr input format
"""

from .event_formatter import format_event_text_repr
from .message_formatter import FormatterOptions, reduce_by_uniform_sampling
from .trace_formatter import format_trace_text_repr, llm_trace_to_formatter_format

__all__ = [
    "FormatterOptions",
    "format_event_text_repr",
    "format_trace_text_repr",
    "llm_trace_to_formatter_format",
    "reduce_by_uniform_sampling",
]
