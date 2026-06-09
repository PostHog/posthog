"""Prompt builders for the agentic changelog-research stage.

The research stage is what replaced the seeded manifest. For each pin the agent reads the vendor's
*actual* changelog/versioning/sunset page and the code site that uses the version, then produces a
``ResearchedDeprecation`` — and may only claim a deprecation it can cite. These builders are pure so
they can be unit-tested without a sandbox; execution happens via ``ApiDeprecationAgent.send()``.
"""

from __future__ import annotations

from products.signals.backend.api_deprecation.schema import Pin

RESEARCH_SYSTEM_NOTE = """You verify whether a single in-code external-API version pin is deprecated, using the vendor's
OWN published changelog / versioning / sunset pages as the source of truth. Rules:

- Ground every claim in the vendor's documentation. Use your web/search tools to read the actual
  changelog or versioning page for this exact vendor and version.
- You may ONLY report `is_deprecated: true` if you can cite it: set `evidence_url` to the specific
  page and `evidence_quote` to the exact text that supports the claim. Never invent a date — if the
  page states no removal date, leave `cutoff_date` null but keep the citation.
- Decide mechanical vs structural by reading the code site (the file/line where we pin the version)
  to see which fields/endpoints WE actually use, then checking whether those change between the
  pinned and recommended version. Unaffected ⇒ mechanical. A field/endpoint/auth WE use changed ⇒
  structural (`affected_fields` lists them). Unsure ⇒ uncertain.
- If you cannot find evidence the version is deprecated, report `is_deprecated: false` — that is a
  valid, expected outcome. Precision over recall: no guesses."""


def build_research_prompt(pin: Pin) -> str:
    """Per-pin research instruction. Pure — embeds the exact pin facts for grounding."""
    return f"""Research whether this pinned API version is deprecated, citing the vendor's changelog.

## The pin (found by the deterministic detector)
- Vendor: {pin.vendor}
- Product: {pin.product}
- API host: {pin.host}
- Pinned version: {pin.pinned_version}
- Code site: `{pin.file}:{pin.line}`{f" (endpoint: {pin.endpoint})" if pin.endpoint else ""}
- Persisted into existing rows: {pin.persisted_per_row} (if true, a fix also needs a data migration)

## What to do
1. Open the code site `{pin.file}` and note exactly which fields/endpoints we send/read against {pin.host}.
2. Find {pin.product}'s changelog / versioning / sunset page and look up **{pin.pinned_version}** and the
   current GA version.
3. Determine: is {pin.pinned_version} deprecated, blocked, or scheduled for removal? If so, the real
   cutoff date (quote it), the recommended version to bump to, and whether any field/endpoint WE use
   changes (mechanical vs structural).

Return a ResearchedDeprecation. Cite your source (`evidence_url` + `evidence_quote`) for any
deprecation claim. If you find no evidence of deprecation, set `is_deprecated: false`."""
