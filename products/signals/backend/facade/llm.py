"""The signals LLM client, for emitters in other products that summarize their input before they emit."""

from products.signals.backend.temporal.llm import call_llm

__all__ = ["call_llm"]
