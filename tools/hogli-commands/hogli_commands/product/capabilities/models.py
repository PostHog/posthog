"""Pydantic models for the derived product capability spec.

The validators here are the enforcement mechanism for the spec's core promise: every
claim is traceable to a file, and anything we cannot compute says so out loud rather
than defaulting to false.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# `unavailable` is a stronger claim than `unknown`: it means we enumerated every place
# this surface could be registered and none named this product. Only closed-world
# derivations may emit it. Anything else is `unknown`.
Availability = Literal["available", "preview", "unavailable", "unknown"]

MatchKind = Literal["exact", "normalized", "alias", "none"]

AVAILABILITY_VALUES: list[Availability] = ["available", "preview", "unavailable", "unknown"]

# Keys that would make this a content artifact rather than a facts artifact. posthog.com
# writes all prose; the repo only states what is true. Asserted over the serialized output.
PROSE_KEYS = frozenset({"description", "summary", "title", "tagline", "docs_url", "copy"})

FactValue = int | str | bool | list[str] | None


class SurfaceFact(BaseModel):
    """One product's verdict on one surface (or data source)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    availability: Availability
    facts: dict[str, FactValue] = Field(default_factory=dict)
    # Repo-relative paths a reviewer can open to re-derive the verdict. Deliberately no
    # line numbers — they churn without changing meaning.
    from_: list[str] = Field(default_factory=list, alias="from")
    unknown_reason: str | None = None

    @model_validator(mode="after")
    def _honesty(self) -> SurfaceFact:
        if self.availability == "unknown":
            if not self.unknown_reason:
                raise ValueError("an `unknown` verdict must explain itself via unknown_reason")
        else:
            if not self.from_:
                raise ValueError(f"a `{self.availability}` verdict must cite at least one source file")
            if self.unknown_reason:
                raise ValueError("unknown_reason is only meaningful on an `unknown` verdict")
        return self


def unknown(reason: str) -> SurfaceFact:
    """The honest answer when a fact cannot be computed."""
    return SurfaceFact(availability="unknown", unknown_reason=reason)


class ProductCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    name: str
    owners: list[str]
    surfaces: dict[str, SurfaceFact]
    data_sources: dict[str, SurfaceFact]


class PlatformFacts(BaseModel):
    """Facts that are genuinely global. A per-product value for these would be invented.

    The Slack CDP destination template, for instance, carries no product attribution at
    all — it is available to every project.
    """

    model_config = ConfigDict(extra="forbid")

    slack_cdp_outbound_destination: bool
    warehouse_signal_sources: list[str] = Field(default_factory=list)
    cli_command_groups: list[str] = Field(default_factory=list)


class UnattributedFacts(BaseModel):
    """The honesty valve: things we found but could not join to a product directory.

    Emitted verbatim rather than dropped or guessed at, so a consumer can see the gap
    and decide what to do about it.
    """

    model_config = ConfigDict(extra="forbid")

    scout_scopes: list[str] = Field(default_factory=list)
    agent_modes: list[str] = Field(default_factory=list)
    max_context_modules: list[str] = Field(default_factory=list)


class CapabilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_version: str
    # Populated only by `--release`. posthog.com uses this to detect a stopped publish;
    # without that check a broken generator serves stale data indefinitely.
    generated_at: str | None = None
    commit_sha: str | None = None
    availability_values: list[Availability] = Field(default_factory=lambda: list(AVAILABILITY_VALUES))
    products: list[ProductCapability]
    platform: PlatformFacts
    unattributed: UnattributedFacts
