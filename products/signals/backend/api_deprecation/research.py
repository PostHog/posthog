"""Prompt builders for the agentic changelog-research stage.

The research stage is what replaced the seeded manifest: for each detected pin the agent reads the
vendor's *actual* changelog and may only claim a deprecation it can cite (enforced by the schema).
These builders are pure strings so they unit-test without a sandbox; execution happens inside the
shared custom-agent workflow via ``ApiDeprecationAgent`` (launched with ``run_agent``).
"""

from __future__ import annotations

from products.signals.backend.api_deprecation.schema import Pin

RESEARCH_SYSTEM_NOTE = """You audit a codebase's pinned external-API versions for deprecations, using each vendor's OWN
published changelog / versioning / sunset pages as the source of truth. Rules:

- Ground every claim in the vendor's documentation. Use your web/search tools to read the actual
  changelog or versioning page for the exact vendor and version.
- You may ONLY report `is_deprecated: true` if you can cite it: set `evidence_url` to the specific
  page and `evidence_quote` to the exact text that supports the claim. Never invent a date — if the
  page states no removal date, leave `cutoff_date` null but keep the citation.
- Decide mechanical vs structural by reading the code site (the file/line where the version is
  pinned) to see which fields/endpoints are used, then checking whether those change between the
  pinned and recommended version. Unaffected ⇒ mechanical. A field/endpoint/auth in use changed ⇒
  structural (list them in `affected_fields`). Unsure ⇒ uncertain.
- If you find no evidence a version is deprecated, report `is_deprecated: false` for it — a valid,
  expected outcome. Precision over recall: no guesses."""

# The single instruction the agent sends after the inventory is in its context.
BATCH_RESEARCH_INSTRUCTION = (
    "Research every pinned version listed in your initial context against its vendor's changelog. "
    "Open each code site to see which fields/endpoints are used. Return a ResearchedDeprecationList "
    "with one item per pin — cite a source (evidence_url + evidence_quote) for any deprecation claim."
)


def _format_pin(pin: Pin) -> str:
    location = f"`{pin.file}:{pin.line}`" + (f" (endpoint {pin.endpoint})" if pin.endpoint else "")
    return (
        f"- {pin.product} — host `{pin.host}`, pinned `{pin.pinned_version}` at {location}; "
        f"persisted_per_row={pin.persisted_per_row} (if true, a fix also needs a data migration)"
    )


def build_research_initial_prompt(pins: list[Pin]) -> str:
    """The agent's ``initial_prompt``: the research persona plus the detector's factual inventory."""
    inventory = "\n".join(_format_pin(pin) for pin in pins) or "(no pins detected)"
    return f"{RESEARCH_SYSTEM_NOTE}\n\n## Detected in-code API version pins\n{inventory}"
