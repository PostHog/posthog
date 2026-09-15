import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.context import EnrichmentPhase as EnrichmentPhase

UNKNOWN: Literal["unknown"] = "unknown"


class GrowthEnrichmentError(Exception):
    pass


class RegionNotAllowed(GrowthEnrichmentError):
    pass


class EnrichmentDisabled(GrowthEnrichmentError):
    pass


class NoRegionalClient(GrowthEnrichmentError):
    pass


class NoActiveScoringLists(GrowthEnrichmentError):
    pass


class ScoringListsIncomplete(GrowthEnrichmentError):
    pass


class LabelConfigNotFound(GrowthEnrichmentError):
    def __init__(self, label: str) -> None:
        super().__init__(f"No active EnrichmentPromptConfig for label {label!r}")
        self.label = label


class LabelVersionMismatch(GrowthEnrichmentError):
    def __init__(self, label: str, active_version: str, expected_version: str) -> None:
        super().__init__(
            f"label {label!r} active version is {active_version!r}, expected {expected_version!r}; "
            "the active version changed after the caller resolved it, aborting"
        )
        self.label = label
        self.active_version = active_version
        self.expected_version = expected_version


class LabelConfigInvalid(GrowthEnrichmentError):
    pass


class LabelBatchLocked(GrowthEnrichmentError):
    def __init__(self, label: str) -> None:
        super().__init__(f"Another enrichment_label_batch run already holds the lock for label {label!r}")
        self.label = label


class LabelCompareVersionNotFound(GrowthEnrichmentError):
    def __init__(self, label: str, version: str) -> None:
        super().__init__(f"No config {version!r} for label {label!r} to compare against")
        self.label = label
        self.version = version


class LabelPromptFileUnreadable(GrowthEnrichmentError):
    def __init__(self, path: str, error: OSError) -> None:
        super().__init__(f"Could not read {path}: {error}")
        self.path = path
        self.error = error


class ScoringListsRejected(GrowthEnrichmentError):
    pass


@frozen
class LabelBatchCounts:
    attempted: int
    succeeded: int
    skipped_existing: int
    skipped_no_ai_consent: int
    unknown: int
    failures: int
    aborted: int
    prompt_tokens: int
    completion_tokens: int


@frozen
class LabelBatchSummary:
    label: str
    prompt_version: str
    counts: LabelBatchCounts
    tried: int
    success_rate: float | None
    elapsed_seconds: float
    circuit_open: bool


@frozen
class LabelOutputField:
    key: str
    type: str


@frozen
class LabelDryRunRow:
    company: str
    signup_domain: str | None = None
    output: dict[str, Any] | None = None
    prior_output: dict[str, Any] | None = None
    error: str | None = None
    skipped_no_ai_consent: bool = False


@frozen
class LabelDryRun:
    display_version: str
    verdict_key: str | None
    output_fields: tuple[LabelOutputField, ...]
    compare_output_fields: tuple[LabelOutputField, ...] | None
    rows: Iterator[LabelDryRunRow]


FitBackfillOutcome = Literal["written", "skipped_org_gone", "skipped_wizard_unavailable"]


@frozen
class FitBackfillItem:
    organization_id: str
    outcome: FitBackfillOutcome
    status: str | None = None
    score: int | None = None


@frozen
class ParityItem:
    domain: str
    status: str
    score: int | None
    diffs: tuple[str, ...] | None


@frozen
class ParityRun:
    expectations: int
    items: Iterator[ParityItem]


FieldsBackfillOutcome = Literal["written", "skipped_no_match", "skipped_empty"]


@frozen
class FieldsBackfillItem:
    organization_id: str
    outcome: FieldsBackfillOutcome
    fields: tuple[str, ...] = ()
    stripped: tuple[str, ...] = ()


SignupSkipReason = Literal["signup_user_left", "no_usable_member"]


@frozen
class SignupCandidate:
    organization_id: str
    created_at: dt.datetime
    distinct_id: str
    domain: str


@frozen
class SignupSkip:
    organization_id: str
    created_at: dt.datetime
    reason: SignupSkipReason


OwnershipOutcome = Literal["no_domain", "fetch_failure", "not_found", "found_no_ownership_status", "classified"]


@frozen
class OwnershipBackfillItem:
    record_id: str
    organization_id: str
    outcome: OwnershipOutcome | None = None
    acquired_or_merged: bool = False
    with_parent: bool = False
    errored: bool = False


@frozen
class OwnershipBackfill:
    total: int
    items: Iterator[OwnershipBackfillItem]


@frozen
class ScoringListsCreated:
    version: str
    is_active: bool
    tag_rows: int
    investor_rows: int
    investors_with_aliases: int
    bucket_counts: tuple[tuple[str, int], ...]
    quality_investors: int
    unrecognized_tokens: tuple[tuple[str, int], ...]


@frozen
class ProductPushCampaignSummary:
    product_key: str
    reason_text: str | None


# Canonical list of the SDK identifiers SDK Health tracks. Lives here (rather than in
# products/growth/dags/github_sdk_versions.py) so non-Dagster consumers — the Temporal
# health check, the API view, and tests — don't need to import from a Dagster module.
SdkTypes = Literal[
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-java",
    "posthog-server",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-kmp",
    "posthog-dotnet",
    "posthog-elixir",
    "posthog-unity",
    "posthog-node-mcp",
    "posthog-python-mcp",
    "posthog-edge",
    "posthog-convex",
    "posthog-rails",
    "posthog-aspnetcore",
]
SDK_TYPES: list[SdkTypes] = [
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-java",
    "posthog-server",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-kmp",
    "posthog-dotnet",
    "posthog-elixir",
    "posthog-unity",
    "posthog-node-mcp",
    "posthog-python-mcp",
    "posthog-edge",
    "posthog-convex",
    "posthog-rails",
    "posthog-aspnetcore",
]
LEGACY_JAVA_SDK = "posthog-java"


class SdkVersionEntry(TypedDict):
    lib_version: str | None
    max_timestamp: str
    count: int


Severity = Literal["none", "warning", "danger"]
OverallHealth = Literal["healthy", "needs_attention"]
DiffKind = Literal["major", "minor", "patch", "extra"]


@dataclass
class SemanticVersion:
    major: int
    minor: Optional[int] = None
    patch: Optional[int] = None
    extra: Optional[str] = None

    def to_string(self) -> str:
        parts = str(self.major)
        if self.minor is not None:
            parts += f".{self.minor}"
            if self.patch is not None:
                parts += f".{self.patch}"
        if self.extra:
            parts += f"-{self.extra}"
        return parts


@dataclass
class SemanticVersionDiff:
    kind: DiffKind
    diff: int


@dataclass
class UsageEntry:
    """Single (version, event_count, release_date) tuple for an SDK."""

    lib_version: str
    count: int
    max_timestamp: str
    release_date: Optional[str] = None
    is_latest: bool = False


@dataclass
class ReleaseAssessment:
    """Per-version outdatedness assessment (corresponds to AugmentedTeamSdkVersionsInfoRelease)."""

    version: str
    count: int
    max_timestamp: str
    release_date: Optional[str]
    days_since_release: Optional[int]
    released_ago: Optional[str]
    is_outdated: bool
    is_old: bool
    needs_updating: bool
    is_current_or_newer: bool
    status_reason: str
    sql_query: str
    activity_page_url: str


@dataclass
class OutdatedTrafficAlert:
    version: str
    threshold_percent: float


@dataclass
class SdkAssessment:
    """Per-SDK health assessment (corresponds to AugmentedTeamSdkVersionsInfo entry)."""

    lib: str
    readable_name: str
    latest_version: str
    needs_updating: bool
    is_outdated: bool
    is_old: bool
    migration_required: bool
    severity: Severity
    reason: str
    banners: list[str] = field(default_factory=list)
    releases: list[ReleaseAssessment] = field(default_factory=list)
    outdated_traffic_alerts: list[OutdatedTrafficAlert] = field(default_factory=list)


@dataclass
class SdkHealthReport:
    """Top-level report returned to agents / frontend."""

    overall_health: OverallHealth
    needs_updating_count: int
    team_sdk_count: int
    health: Literal["success", "warning", "danger"]
    sdks: list[SdkAssessment] = field(default_factory=list)
