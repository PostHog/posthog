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
    "with one item per pin — copy each item's `pin` object verbatim from the inventory JSON, and "
    "cite a source (evidence_url + evidence_quote) for any deprecation claim."
)


def build_research_initial_prompt(pins: list[Pin]) -> str:
    """The agent's ``initial_prompt``: the research persona plus the detector's factual inventory.

    Pins are embedded as one JSON object per line so the research output can echo each ``pin``
    verbatim — the report renders pin fields (vendor, file, line, persisted_per_row) straight from
    the echoed objects, so a paraphrased pin (e.g. ``vendor: "Meta"`` instead of ``"meta"``) would
    corrupt the report.
    """
    inventory = "\n".join(pin.model_dump_json() for pin in pins) or "(no pins detected)"
    return (
        f"{RESEARCH_SYSTEM_NOTE}\n\n"
        "## Detected in-code API version pins (one JSON object per line)\n"
        f"{inventory}\n\n"
        "In your research output, copy each `pin` object verbatim from this inventory — do not rename, "
        "reformat, or drop fields. `persisted_per_row: true` means the version is baked into persisted "
        "rows, so a fix also needs a data migration, not just a source bump."
    )
