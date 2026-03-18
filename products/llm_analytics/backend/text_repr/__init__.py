"""
LLM Analytics Text Representation Module

Provides formatters for converting LLM trace events to human-readable text.

Architecture:
- Frontend: Calls Django REST API at /api/llm_analytics/text_repr/
- Python backend: Imports formatters directly (no API call needed)
"""

from .formatters import format_event_text_repr, format_trace_text_repr

__all__ = [
    "format_event_text_repr",
    "format_trace_text_repr",
]
