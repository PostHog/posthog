"""Shared LLM utilities for surveys."""

from .gateway import generate_structured_output as generate_structured_output_via_gateway

__all__ = ["generate_structured_output_via_gateway"]
