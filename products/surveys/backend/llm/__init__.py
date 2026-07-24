"""Shared LLM utilities for surveys."""

from .client import create_gemini_client, generate_structured_output
from .gateway import generate_structured_output as generate_structured_output_via_gateway

__all__ = ["create_gemini_client", "generate_structured_output", "generate_structured_output_via_gateway"]
