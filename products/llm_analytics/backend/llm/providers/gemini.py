"""Deprecated shim for legacy imports. Use google.py instead."""

from .google import GeminiAdapter, GeminiConfig, GeminiProvider

__all__ = ["GeminiConfig", "GeminiAdapter", "GeminiProvider"]
