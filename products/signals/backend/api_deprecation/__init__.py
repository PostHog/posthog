"""API deprecation detection for the Signals inbox.

A deterministic **detector** (``scanner.scan_repo`` + ``extractors``) produces a factual inventory of
where the codebase pins external-API versions — vendor/host/version/file/line, no dates, no claims.
The agentic research that turns each pin into a *cited* ``ResearchedDeprecation`` (dates +
mechanical/structural, with citation enforced by ``schema``) runs in ``agent.ApiDeprecationAgent``
on the shared custom-agent rails.
"""

from products.signals.backend.api_deprecation.schema import Classification, Pin, ResearchedDeprecation

__all__ = ["Classification", "Pin", "ResearchedDeprecation"]
