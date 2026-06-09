"""API deprecation watch loop.

Two stages with a deliberate boundary:

1. **Detector** (deterministic, ``scanner.scan_repo`` + ``extractors``): a factual inventory of where
   the codebase pins external-API versions — vendor/host/version/file/line. No dates, no claims.
2. **Research** (agentic, ``agent.ApiDeprecationAgent``): per pin, reads the vendor's real changelog
   and produces a *cited* ``ResearchedDeprecation``. Dates + mechanical/structural come from here;
   a deprecation claim without a citation is rejected (``schema``). No seeded sunset tables.

``emit`` lands the cited findings in the Signals inbox (PostHog Code); ``dispatch`` routes mechanical
findings to PostHog Code (draft PRs) and structural ones to humans (issues). See README.md.
"""

from products.signals.backend.api_deprecation.schema import Classification, Pin, ResearchedDeprecation

__all__ = ["Classification", "Pin", "ResearchedDeprecation"]
