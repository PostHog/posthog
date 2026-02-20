"""Deprecated shim for legacy imports. Use google.py instead."""

from .google import GeminiToolFormatter, GoogleToolFormatter

__all__ = ["GoogleToolFormatter", "GeminiToolFormatter"]
