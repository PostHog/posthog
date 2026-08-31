"""Frozen, framework-free contracts for proactive subscription work."""

from dataclasses import field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

ActionKind = Literal["draft_pr", "experiment_draft", "recommendation", "combined"]


@frozen
class ProactiveConfigInput:
    enabled: bool = False
    repository: str | None = None
    repository_integration_id: int | None = None
    create_draft_pr: bool = False
    repository_grant_id: UUID | None = None
    public_research_subject_id: UUID | None = None


@frozen
class ProactiveConfigDTO:
    enabled: bool
    repository: str | None
    repository_integration_id: int | None
    create_draft_pr: bool
    repository_grant_id: UUID | None
    public_research_subject_id: UUID | None


@frozen
class RepositoryOptionDTO:
    repository: str
    repository_integration_id: int


@frozen
class PublicResearchSubjectOptionDTO:
    id: UUID
    display_name: str
    canonical_domain: str


@frozen
class ProactiveConfigurationOptionsDTO:
    proactive_available: bool
    draft_pr_available: bool
    repositories: list[RepositoryOptionDTO]
    public_research_subjects: list[PublicResearchSubjectOptionDTO]


@frozen
class GoalNormalizationInput:
    original_prompt: str
    repositories: list[str] = field(default_factory=list)
    identities: list[int] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    artifact_types: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)


@frozen
class GoalNormalizationCandidate:
    goal_statement: str
    decision_constraints: list[str]
    repositories: list[str]
    identities: list[int]
    metrics: list[str]
    artifact_types: list[str]
    permissions: list[str]


@frozen
class GoalNormalizationResult:
    goal_statement: str
    decision_constraints: list[str]
    prompt_version: str
    model_version: str | None
    valid: bool
    failure_code: str | None = None


@frozen
class MeasurementCandidate:
    """Model-supplied measurement intent, before server-owned canonicalization."""

    run_id: UUID
    baseline_tool_call_id: str
    metric_name: str
    metric_unit: Literal["count", "ratio", "percent", "currency", "duration", "other"]
    direction: Literal["increase", "decrease", "maintain"]
    expected_change_type: Literal["absolute", "relative_percent"]
    expected_change_lower: Decimal
    expected_change_upper: Decimal
    readout_after_days: int
    selector: dict[str, str]


@frozen
class MeasurementEvidence:
    """Authorized, decrypted evidence passed from the Pulse boundary to an adapter."""

    run_id: UUID
    tool_call_id: str
    tool_name: str
    tool_schema_version: str
    arguments: dict[str, object]
    result: object
    completed_at: datetime | None
    error_class: str | None = None
    result_truncated: bool = False


@frozen
class CanonicalMeasurement:
    """Server-owned replay spec plus the extracted baseline."""

    spec: dict[str, object]
    metric_name: str
    metric_unit: Literal["count"]
    baseline_value: Decimal
    baseline_from: datetime
    baseline_to: datetime


@frozen
class OutcomeEvaluation:
    status: Literal["measured", "inconclusive"]
    observed_value: Decimal | None
    observed_from: datetime | None
    observed_to: datetime | None
    absolute_delta: Decimal | None
    relative_delta: Decimal | None
    verdict: Literal["improved", "flat", "regressed", "inconclusive"]
    failure_code: str | None = None


@frozen
class OutcomeReplayInstructionDTO:
    """The one server-derived measurement call a claimed readout may replay."""

    plan_id: UUID
    tool_name: str
    tool_schema_version: str
    comparison_arguments: dict[str, object]
    selector: dict[str, str]


@frozen
class OutcomeMemoryProposalDTO:
    opportunity_key: str
    action_key: str
    kind: str
    target_category: str
    metric_name: str
    adoption_status: str
    readout_status: str
    adoption_source: str | None
    verdict: str | None
    last_seen_at: datetime
    terminal_at: datetime | None


@frozen
class OutcomeMemoryBucketDTO:
    kind: str
    target_category: str
    total: int
    adopted: int
    measured: int
    inconclusive: int
    improved: int
    adoption_rate: Decimal | None
    improvement_rate: Decimal | None


@frozen
class OutcomeMemoryDTO:
    version: int
    proposals: tuple[OutcomeMemoryProposalDTO, ...]
    buckets: tuple[OutcomeMemoryBucketDTO, ...]
    rows_considered: int
    truncated: bool


@frozen
class EvidenceProvenanceDTO:
    tool_name: str
    tool_schema_version: str
    started_at: datetime | None
    completed_at: datetime | None
    result_truncated: bool
    error_class: str | None


@frozen
class EvidenceAuditDTO:
    id: UUID
    tool_call_id: str
    completed_at: datetime | None
    result_truncated: bool
    error_class: str | None


@frozen
class PublicResearchCitationDTO:
    evidence_id: UUID
    canonical_url: str
    title: str | None
    retrieved_at: datetime
    excerpt: str


@frozen
class PublicResearchCitationHistoryDTO:
    evidence_id: UUID
    canonical_url: str
    title: str | None
    retrieved_at: datetime


@frozen
class PublicationGateHistoryDTO:
    label: str
    status: str


@frozen
class BuildTestGateSummaryDTO:
    status: str
    completed_at: datetime | None
    failure_code: str | None
    gates: list[PublicationGateHistoryDTO]


@frozen
class ArtifactLinkDTO:
    kind: str
    status: str
    external_url: str | None
    external_state: str | None
    failure_code: str | None
    task_id: UUID | None
    execution_task_run_id: UUID | None
    experiment_id: int | None


@frozen
class RunActionHistoryDTO:
    id: UUID
    action_key: str
    kind: str
    title: str
    rationale: str
    expected_impact: str
    rank: int
    implementation_selected: bool
    status: str
    why_now: str | None
    confidence: Decimal | None
    effort: str
    metric_name: str | None
    metric_unit: str | None
    metric_direction: str | None
    expected_change_type: str | None
    expected_change_lower: Decimal | None
    expected_change_upper: Decimal | None
    readout_after_days: int | None
    plan_id: UUID | None
    baseline_value: Decimal | None
    baseline_from: datetime | None
    baseline_to: datetime | None
    adoption_status: str | None
    adoption_source: str | None
    adopted_at: datetime | None
    decision_at: datetime | None
    decided_by_id: int | None
    readout_status: str | None
    next_readout_at: datetime | None
    evidence: list[EvidenceProvenanceDTO]
    citations: list[PublicResearchCitationHistoryDTO]
    build_test_gate: BuildTestGateSummaryDTO | None
    artifacts: list[ArtifactLinkDTO]


@frozen
class DeliveryHistoryDTO:
    status: str
    failure_code: str | None
    accepted_at: datetime | None


@frozen
class OutcomeReadoutHistoryDTO:
    id: UUID
    plan_id: UUID
    action_id: UUID
    recommendation_title: str
    metric_name: str
    metric_unit: Literal["count"]
    baseline_value: Decimal
    baseline_from: datetime
    baseline_to: datetime
    observed_value: Decimal | None
    observed_from: datetime | None
    observed_to: datetime | None
    absolute_delta: Decimal | None
    relative_delta: Decimal | None
    status: str
    verdict: str
    confidence: Decimal | None
    failure_code: str | None
    artifacts: list[ArtifactLinkDTO]


@frozen
class PulseRunHistoryDTO:
    id: UUID
    subscription_id: int
    delivery_id: UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    task_id: UUID | None
    analysis_task_run_id: UUID | None
    execution_task_run_id: UUID | None
    failure_code: str | None
    skip_reason: str | None
    deliveries: list[DeliveryHistoryDTO]
    readouts: list[OutcomeReadoutHistoryDTO]
    actions: list[RunActionHistoryDTO]


@frozen
class ActedOnUpdateInput:
    acted_on: bool


@frozen
class ActedOnUpdateDTO:
    id: UUID
    acted_on: bool
    acted_on_at: datetime | None
    acted_on_by_id: int | None


@frozen
class OutcomeDecisionDTO:
    plan_id: UUID
    action_id: UUID
    adoption_status: Literal["adopted", "dismissed"]
    readout_status: str
    adopted_at: datetime | None
    decision_at: datetime
    decided_by_id: int
    next_readout_at: datetime | None


@frozen
class PulseExperimentDraftResultDTO:
    artifact_id: UUID
    action_id: UUID
    experiment_id: int
    feature_flag_id: int
    status: Literal["verified"]
    created: bool


@frozen
class PulseRunSnapshotInput:
    delivery_id: UUID
    report_snapshot_ref: str
    original_prompt: str
    contexts: list[dict[str, int]]
    limits: dict[str, int]
    flags: dict[str, bool]
    actor_id: int
    integration_id: int | None
    model_version: str | None
    normalizer_model_version: str | None
    normalizer_candidate: GoalNormalizationCandidate | None = None


@frozen
class PulseRunCreationInput:
    """Trusted delivery snapshot used to create exactly one durable Pulse run."""

    team_id: int
    subscription_id: int
    delivery_id: UUID
    report_snapshot_ref: str
    config_snapshot: dict[str, object]
    wall_clock_deadline_at: datetime | None = None
    finalization_margin_seconds: int = 0


@frozen
class PulseAnalysisActionInput:
    """One bounded, structured action emitted by the analysis task."""

    opportunity_key: str
    opportunity_title: str
    opportunity_summary: str
    action_key: str
    kind: ActionKind
    title: str
    rationale: str
    expected_impact: str
    rank: int
    normalized_target: dict[str, str]
    evidence_tool_call_ids: tuple[str, ...] = ()
    why_now: str = ""
    confidence: Decimal = Decimal("-1")
    effort: Literal["small", "medium", "large"] | str = ""
    metric_name: str = ""
    metric_unit: Literal["count", "ratio", "percent", "currency", "duration", "other"] | str = ""
    metric_direction: Literal["increase", "decrease", "maintain"] | str = ""
    expected_change_type: Literal["absolute", "relative_percent"] | str = ""
    expected_change_lower: Decimal = Decimal("0")
    expected_change_upper: Decimal = Decimal("0")
    readout_after_days: int = 0
    selector: dict[str, str] = field(default_factory=dict)
    baseline_tool_call_id: str = ""


@frozen
class PulseAnalysisPersistenceInput:
    """Caller-bound result persistence request for an analysis task."""

    team_id: int
    run_id: UUID
    task_id: UUID
    analysis_task_run_id: UUID
    selected_action_key: str | None
    actions: tuple[PulseAnalysisActionInput, ...]
    readouts: "tuple[PulseOutcomeReadoutInput, ...]" = ()


@frozen
class PulseAnalysisPersistenceDTO:
    run_id: UUID
    action_ids: tuple[UUID, ...]
    artifact_ids: tuple[UUID, ...]


@frozen
class ClaimedOutcomeDTO:
    """A bounded reference to a plan claimed by this normal Pulse delivery."""

    plan_id: UUID
    source_action_id: UUID
    measurement_spec_version: int


@frozen
class PulseOutcomeReadoutInput:
    """One server-owned outcome result, bound to a plan claimed by this run."""

    plan_id: UUID
    evidence_tool_call_id: str | None = None
    failure_code: str | None = None
    not_ready: bool = False


@frozen
class PulseOutcomeReadoutPersistenceInput:
    team_id: int
    run_id: UUID
    now: datetime
    readouts: tuple[PulseOutcomeReadoutInput, ...]


@frozen
class OutcomeObservationDTO:
    id: UUID
    plan_id: UUID
    attempt_number: int
    status: Literal["measured", "inconclusive", "failed"]
    verdict: Literal["improved", "flat", "regressed", "inconclusive"]


@frozen
class PulseReaperResult:
    reconciled_count: int
    purged_evidence_count: int


@frozen
class BeginPulseDeliveryBundleInput:
    team_id: int
    ledger_id: UUID


@frozen
class PulseDeliveryBundleAttemptDTO:
    provider_idempotency_key: str
    content: bytes = field(repr=False)


@frozen
class FinishPulseDeliveryBundleInput:
    team_id: int
    ledger_id: UUID
    outcome: Literal["accepted", "failed", "delivery_unknown"]
    failure_code: str | None = None
