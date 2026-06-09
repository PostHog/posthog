"""Types for the API deprecation watch loop.

Two clean stages with a deliberate boundary:

- ``Pin`` — the **deterministic detector** output: a factual inventory of where the codebase pins an
  external-API version. No dates, no deprecation claims — only what is literally in the code.
- ``ResearchedDeprecation`` — the **agentic research** output: a per-pin assessment grounded in the
  vendor's actual changelog, with a required citation. Dates and the mechanical/structural call come
  from here, never from a hand-seeded table. No citation ⇒ no dated claim (enforced below).

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
    """Whether a deprecation can be auto-remediated — derived from the field-level changelog review.

    MECHANICAL — pure version-number bump, API shape unchanged for the fields/endpoints we use → auto-PR.
    STRUCTURAL — endpoint/auth/payload changed (e.g. Google Ads API → Data Manager API) → humans only.
    UNCERTAIN — research could not confidently tell → treat as structural, never auto-PR.
    """

    MECHANICAL = "mechanical"
    STRUCTURAL = "structural"
    UNCERTAIN = "uncertain"


class Pin(BaseModel):
    """A single in-code external-API version pin (deterministic detector output)."""

    vendor: str = Field(description="Vendor key, e.g. 'meta', 'google_ads'.")
    product: str = Field(description="Human label, e.g. 'Meta Graph API (WhatsApp destination)'.")
    host: str = Field(description="API host the pin targets, e.g. 'graph.facebook.com'.")
    pinned_version: str = Field(description="The literal pinned version, e.g. 'v21.0'.")
    file: str = Field(description="Repo-relative path of the file containing the pin.")
    line: int = Field(description="1-based line number of the pin.")
    endpoint: str | None = Field(default=None, description="URL/endpoint shape the pin is used in, if captured.")
    extractor: str = Field(description="Which extractor matched (traceability).")
    is_test_file: bool = Field(default=False)
    persisted_per_row: bool = Field(
        default=True,
        description="True if the version is compiled into persisted rows (CDP destination templates bake "
        "it into HogFunction.hog), so a fix also needs a data migration — not just a source bump.",
    )


class ResearchedDeprecation(BaseModel):
    """A pin's deprecation assessment, grounded in the vendor changelog (agentic research output).

    A claim that a pin is deprecated MUST cite a source — ``evidence_url`` + ``evidence_quote`` are
    required when ``is_deprecated`` is true. This is the structural guard against fabricated dates:
    the research stage cannot assert a deprecation it cannot cite.
    """

    pin: Pin
    is_deprecated: bool = Field(description="Whether the pinned version is deprecated/blocked or scheduled to be.")
    cutoff_date: date | None = Field(
        default=None,
        description="Real removal/sunset date from the changelog, if the source states one. "
        "May be null for 'deprecated, no published date' — still requires a citation.",
    )
    already_past_cutoff: bool = Field(default=False, description="True if the cutoff date is in the past.")
    latest_ga_version: str | None = Field(default=None)
    recommended_version: str | None = Field(default=None, description="Version to bump to.")
    classification: Classification = Field(default=Classification.UNCERTAIN)
    affected_fields: list[str] = Field(
        default_factory=list,
        description="Fields/endpoints we use that change between the pinned and recommended version. "
        "Empty ⇒ mechanical; non-empty ⇒ structural.",
    )
    evidence_url: str = Field(default="", description="The specific changelog/versioning page the claim rests on.")
    evidence_quote: str = Field(default="", description="The cited text from that page supporting the claim.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="Short, evidence-grounded rationale.")

    @model_validator(mode="after")
    def _require_citation_for_deprecation(self) -> ResearchedDeprecation:
        if self.is_deprecated and not (self.evidence_url.strip() and self.evidence_quote.strip()):
            raise ValueError(
                "A deprecation claim requires a citation: both evidence_url and evidence_quote must be set."
            )
        return self

    @property
    def dedup_key(self) -> str:
        """Stable key so a re-run doesn't refile an already-open signal."""
        return f"{self.pin.vendor}:{self.pin.host}:{self.pin.pinned_version}:{self.pin.file}"


class ResearchedDeprecationList(BaseModel):
    """Batched research output — one assessment per detected pin."""

    items: list[ResearchedDeprecation] = Field(default_factory=list)
