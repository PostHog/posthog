"""Third-party API deprecation detection for the Signals inbox.

A deterministic **detector** (``scanner.scan_repo`` + ``extractors``) produces a factual inventory
of the codebase's external URL usages — host/endpoint/version/file/line, no dates, no claims. The
agentic stage that triages which usages are genuine API call sites and turns each into a *cited*
``ResearchedDeprecation`` (dates + mechanical/structural, with citation enforced by ``schema``)
runs in ``agent.ApiDeprecationAgent`` on the shared custom-agent rails.
"""

from products.signals.backend.api_deprecation.schema import ApiUsage, Classification, ResearchedDeprecation

__all__ = ["ApiUsage", "Classification", "ResearchedDeprecation"]
