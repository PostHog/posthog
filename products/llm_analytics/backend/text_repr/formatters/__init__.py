"""
Text representation formatters for LLM Analytics events.

Pure Python implementation for formatting $ai_generation, $ai_span, and $ai_trace events
into human-readable text representations.

Main entry points:
- format_event_text_repr: Format single events ($ai_generation, $ai_span)
- format_trace_text_repr: Format full traces with hierarchy
"""

from .text_formatter import format_event_text_repr
from .trace_formatter import format_trace_text_repr

__all__ = [
    "format_event_text_repr",
    "format_trace_text_repr",
]
