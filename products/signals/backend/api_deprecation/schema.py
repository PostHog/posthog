"""Types for the API deprecation watch loop.

Two clean stages with a deliberate boundary:

- ``ApiUsage`` — the **deterministic detector** output: a factual inventory of where the codebase
  references third-party URLs — host/endpoint/version/file/line. No dates, no claims, and no
  judgment about which references are genuine API call sites — only what is literally in the code.
- ``ResearchedDeprecation`` — the **agentic research** output: triage (which usages are real API
  call sites) plus a per-usage assessment grounded in the vendor's official documentation, with a
  required citation. Dates, fix headlines, and the mechanical/structural call come from here, never
  from a hand-seeded table. No citation ⇒ no deprecation claim (enforced below).

Kept free of Django imports so the detector + the pure helpers stay trivially unit-testable.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator

Severity = str  # one of "P0".."P3" (mirrors products.signals...research.Priority by value)
VALID_SEVERITIES = ("P0", "P1", "P2", "P3")

# A finding is auto-remediable (mechanical → draft PR) only at or above this confidence; below it, or
# if structural/uncertain, it goes to a human. Shared by the inbox render and the dispatch router.
MECHANICAL_CONFIDENCE_THRESHOLD = 0.8


class Classification(str, Enum):
    """Whether a deprecation can be auto-remediated — derived from the field-level documentation review.

    MECHANICAL — pure version-number bump, API shape unchanged for the fields/endpoints we use → auto-PR.
    STRUCTURAL — endpoint/auth/payload changed (e.g. Google Ads API → Data Manager API) → humans only.
    UNCERTAIN — research could not confidently tell → treat as structural, never auto-PR.
    """

    MECHANICAL = "mechanical"
    STRUCTURAL = "structural"
    UNCERTAIN = "uncertain"


class ApiUsage(BaseModel):
    """A single in-code external URL usage (deterministic detector output).

    Deliberately inclusive: API call sites, documentation links, OAuth scope identifiers, and static
    assets all appear here. Triaging which ones are genuine API calls is the research agent's first
    job — it can open the code; the detector must not guess.
    """

    host: str = Field(description="The URL's host, e.g. 'googleads.googleapis.com'.")
    endpoint: str = Field(
        description="The URL's path with interpolations collapsed to {…}, "
        "e.g. '/v21/customers/{…}:uploadClickConversions'. Empty for bare-host references.",
    )
    version: str | None = Field(
        default=None,
        description="The pinned API version if one is literal in the code ('v21', 'v25.0'), else null.",
    )
    file: str = Field(description="Repo-relative path of the file containing the usage.")
    line: int = Field(description="1-based line number of the usage's first occurrence.")
    extractor: str = Field(description="Which extraction rule produced this row (traceability).")
    is_test_file: bool = Field(default=False)
    persisted_per_row: bool = Field(
        default=True,
        description="True if the code is compiled into persisted rows (CDP destination templates bake "
        "it into HogFunction.hog), so a fix also needs a data migration — not just a source bump.",
    )


class ResearchedDeprecation(BaseModel):
    """A usage's deprecation assessment, grounded in vendor documentation (agentic research output).

    A claim that a usage is deprecated MUST cite a source — ``evidence_url`` + ``evidence_quote`` are
    required when ``is_deprecated`` is true, along with a ``headline`` naming the fix. This is the
    structural guard against fabricated findings: the research stage cannot assert a deprecation it
    cannot cite.
    """

    usage: ApiUsage = Field(description="The detected usage, copied verbatim from the inventory.")
    is_deprecated: bool = Field(
        description="Whether the usage is deprecated/blocked or scheduled to be — at the version "
        "level (pinned version sunset) or the endpoint/product level (endpoint sunset while the "
        "version is current).",
    )
    headline: str = Field(
        default="",
        max_length=80,
        description="Imperative one-liner naming the fix, e.g. 'Bump Meta Graph API v21.0 → v25.0' "
        "or 'Migrate Google Ads uploadClickConversions to Data Manager events:ingest'. "
        "Required for any deprecation claim.",
    )
    cutoff_date: date | None = Field(
        default=None,
        description="Real removal/sunset date from the vendor's documentation, if the source states "
        "one. May be null for 'deprecated, no published date' — still requires a citation.",
    )
    recommended_version: str | None = Field(
        default=None, description="Version to bump to, when the fix is a version bump."
    )
    classification: Classification = Field(default=Classification.UNCERTAIN)
    affected_fields: list[str] = Field(
        default_factory=list,
        description="Fields/endpoints we use that change between the current and recommended usage. "
        "Empty ⇒ mechanical; non-empty ⇒ structural.",
    )
    evidence_url: str = Field(default="", description="The specific vendor page the claim rests on.")
    evidence_quote: str = Field(default="", description="The cited text from that page supporting the claim.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="Short, evidence-grounded rationale.")

    @model_validator(mode="after")
    def _require_citation_for_deprecation(self) -> ResearchedDeprecation:
        if self.is_deprecated and not (
            self.evidence_url.strip() and self.evidence_quote.strip() and self.headline.strip()
        ):
            raise ValueError(
                "A deprecation claim requires a citation and a fix headline: "
                "evidence_url, evidence_quote, and headline must all be set."
            )
        return self


class ResearchedDeprecationList(BaseModel):
    """Batched research output: cited deprecations plus the triage of everything else."""

    items: list[ResearchedDeprecation] = Field(
        default_factory=list,
        description="One item per cited deprecation. Do not include usages you could not cite.",
    )
    cleared: list[str] = Field(
        default_factory=list,
        description="'host + endpoint' of genuine API usages researched and verified current.",
    )
    skipped: list[str] = Field(
        default_factory=list,
        description="'host + endpoint' of inventory entries triaged as not API call sites "
        "(documentation links, OAuth scopes, static assets, UI links).",
    )
