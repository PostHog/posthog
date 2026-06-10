"""Prompt builders for the agentic triage + research stage.

The detector hands over a deliberately inclusive inventory of external URL usages; the agent first
triages which entries are genuine API call sites (it can open the code), then researches those
against the vendor's *official* documentation — at both the version level and the endpoint/product
level — and may only claim a deprecation it can cite (enforced by the schema).
These builders are pure strings so they unit-test without a sandbox; execution happens inside the
shared custom-agent workflow via ``ApiDeprecationAgent`` (launched with ``run_agent``).
"""

from __future__ import annotations

from products.signals.backend.api_deprecation.schema import ApiUsage

RESEARCH_SYSTEM_NOTE = """You audit a codebase's third-party API usage for deprecations, using each vendor's OWN published
documentation (changelogs, deprecation schedules, migration guides) as the source of truth. Rules:

- The inventory you receive is a raw, deliberately inclusive list of external URLs found in the
  code. Your first job is triage: open each code site and decide which entries are genuine API call
  sites. Documentation links, OAuth scope identifiers, static assets, and UI links are not — record
  those in `skipped` and spend no research on them.
- For each genuine call site, check BOTH axes: (a) the pinned version — is it deprecated/blocked or
  scheduled to be; and (b) the endpoint or API product itself — vendors sunset endpoints while the
  version is still current, so a current version is not evidence the usage is safe.
- You may ONLY report a deprecation if you can cite it: set `evidence_url` to the specific vendor
  page and `evidence_quote` to the exact text that supports the claim, and name the fix in
  `headline`. Never invent a date — if the page states no removal date, leave `cutoff_date` null
  but keep the citation.
- Decide mechanical vs structural by reading the code site to see which fields/endpoints are used,
  then checking whether those change in the recommended target. Unaffected ⇒ mechanical. A
  field/endpoint/auth in use changes ⇒ structural (list them in `affected_fields`). Unsure ⇒
  uncertain.
- Genuine usages you research and find current go in `cleared` — a valid, expected outcome.
  Precision over recall: no guesses."""

# The single instruction the agent sends after the inventory is in its context.
BATCH_RESEARCH_INSTRUCTION = (
    "Triage and research every usage listed in your initial context. Open each code site, decide "
    "which entries are genuine third-party API call sites, then research those against the vendor's "
    "official documentation — both version-level deprecations and endpoint/product-level sunsets. "
    "Return a ResearchedDeprecationList: one item per deprecation you can cite (copy the `usage` "
    "object verbatim from the inventory JSON), `cleared` for genuine usages you verified current, "
    "`skipped` for entries that are not API call sites."
)


def build_research_initial_prompt(usages: list[ApiUsage]) -> str:
    """The agent's ``initial_prompt``: the research persona plus the detector's factual inventory.

    Usages are embedded as one JSON object per line so the research output can echo each ``usage``
    verbatim — the report renders usage fields (host, endpoint, file, line, persisted_per_row)
    straight from the echoed objects, so a paraphrased usage would corrupt the report.
    """
    inventory = "\n".join(usage.model_dump_json() for usage in usages) or "(no usages detected)"
    return (
        f"{RESEARCH_SYSTEM_NOTE}\n\n"
        "## Detected external URL usages (one JSON object per line)\n"
        f"{inventory}\n\n"
        "In your research output, copy each `usage` object verbatim from this inventory — do not "
        "rename, reformat, or drop fields. `persisted_per_row: true` means the code is baked into "
        "persisted rows, so a fix also needs a data migration, not just a source change."
    )
