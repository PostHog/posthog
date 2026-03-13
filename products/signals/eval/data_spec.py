from dataclasses import dataclass
from enum import StrEnum


class SourceProducts(StrEnum):
    ZENDESK = "zendesk"
    GITHUB = "github"
    LINEAR = "linear"


class SourceTypes(StrEnum):
    ISSUE = "issue"
    TICKET = "ticket"


@dataclass
class SignalSpec:
    """Specification for a single synthetic signal."""

    source_product: SourceProducts  # zendesk, github, linear
    source_type: SourceTypes  # ticket, issue
    style: str  # bug, support, feature, internal, slack, community
    description: str  # one-sentence description of what this specific signal should say


@dataclass
class GroupSpec:
    """Specification for a single synthetic group."""

    scenario: str  # a description of the scenario causing the signals
    signals: list[SignalSpec]
