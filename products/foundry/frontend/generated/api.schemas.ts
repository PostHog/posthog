/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * How the bet should be rolled out once gated (free-form, consumed by the orchestrator).
 */
export type BetDTOApiExposurePlan = { [key: string]: unknown }

export interface SuccessMetricApi {
    /** Human-readable name of the metric the bet is judged on. */
    name: string
    /** Target for the metric, e.g. '+10%' or '>= 0.42'. Free-form; the experiment carries the formal definition. */
    target?: string
    /** Optional longer description of how the metric is measured. */
    description?: string
}

export interface GuardrailApi {
    /** Name of the guardrail metric that must not regress. */
    name: string
    /** Constraint the guardrail enforces, e.g. 'error rate must not rise'. */
    constraint?: string
}

export interface BudgetApi {
    /** Maximum spend for the bet's execution, in USD. */
    usd?: number
    /** Wall-clock budget for the bet, in hours. */
    time_hours?: number
    /** Maximum number of build iterations before the bet expires. */
    iterations?: number
}

export interface SourceRefApi {
    /** Short label for the lineage source, e.g. 'signal: checkout error spike'. */
    label: string
    /** Link to the originating signal or report. */
    url?: string
}

/**
 * * `drafted` - DRAFTED
 * * `funded` - FUNDED
 * * `building` - BUILDING
 * * `gated` - GATED
 * * `exposed` - EXPOSED
 * * `archived` - ARCHIVED
 */
export type BetDTOStateEnumApi = (typeof BetDTOStateEnumApi)[keyof typeof BetDTOStateEnumApi]

export const BetDTOStateEnumApi = {
    Drafted: 'drafted',
    Funded: 'funded',
    Building: 'building',
    Gated: 'gated',
    Exposed: 'exposed',
    Archived: 'archived',
} as const

/**
 * * `promoted` - PROMOTED
 * * `rolled_back` - ROLLED_BACK
 * * `iterate` - ITERATE
 */
export type BetDTOVerdictEnumApi = (typeof BetDTOVerdictEnumApi)[keyof typeof BetDTOVerdictEnumApi]

export const BetDTOVerdictEnumApi = {
    Promoted: 'promoted',
    RolledBack: 'rolled_back',
    Iterate: 'iterate',
} as const

export interface BetDTOApi {
    /** The single metric that decides whether the bet wins. */
    success_metric: SuccessMetricApi
    /** Metrics that must not regress while the bet is exposed. */
    guardrails: GuardrailApi[]
    /** Resource ceiling for autonomous execution. */
    budget: BudgetApi
    /** How the bet should be rolled out once gated (free-form, consumed by the orchestrator). */
    exposure_plan: BetDTOApiExposurePlan
    /** Lineage references to the signals/reports that motivated the bet. */
    sources: SourceRefApi[]
    id: string
    slug: string
    hypothesis: string
    /** @nullable */
    ttl: string | null
    state: BetDTOStateEnumApi
    verdict: BetDTOVerdictEnumApi | null
    iteration: number
    /** @nullable */
    feature_flag_id: number | null
    /** @nullable */
    feature_flag_key: string | null
    /** @nullable */
    experiment_id: number | null
    created_at: string
    updated_at: string
}

/**
 * How the bet should be rolled out once gated (free-form, consumed by the orchestrator).
 */
export type CreateBetApiExposurePlan = { [key: string]: unknown }

export interface CreateBetApi {
    /**
     * Unique-per-project identifier; also seeds the feature flag key ('bet-<slug>').
     * @maxLength 200
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /** The falsifiable statement this bet exists to test. */
    hypothesis: string
    /** The single metric that decides whether the bet wins. */
    success_metric: SuccessMetricApi
    /** Metrics that must not regress while the bet is exposed. */
    guardrails?: GuardrailApi[]
    /** Resource ceiling for autonomous execution. */
    budget?: BudgetApi
    /** How the bet should be rolled out once gated (free-form, consumed by the orchestrator). */
    exposure_plan?: CreateBetApiExposurePlan
    /** Lineage references to the signals/reports that motivated the bet. */
    sources?: SourceRefApi[]
    /**
     * When the bet expires if unresolved.
     * @nullable
     */
    ttl?: string | null
}

/**
 * Event payload as reported by the orchestrator.
 */
export type BetEventDTOApiPayload = { [key: string]: unknown }

/**
 * * `run.started` - RUN_STARTED
 * * `run.finished` - RUN_FINISHED
 * * `node.spawned` - NODE_SPAWNED
 * * `artifact.ready` - ARTIFACT_READY
 * * `gate.result` - GATE_RESULT
 * * `exposure.started` - EXPOSURE_STARTED
 * * `verdict.proposed` - VERDICT_PROPOSED
 * * `note` - NOTE
 * * `state.changed` - STATE_CHANGED
 */
export type BetEventDTOKindEnumApi = (typeof BetEventDTOKindEnumApi)[keyof typeof BetEventDTOKindEnumApi]

export const BetEventDTOKindEnumApi = {
    Runstarted: 'run.started',
    Runfinished: 'run.finished',
    Nodespawned: 'node.spawned',
    Artifactready: 'artifact.ready',
    Gateresult: 'gate.result',
    Exposurestarted: 'exposure.started',
    Verdictproposed: 'verdict.proposed',
    Note: 'note',
    Statechanged: 'state.changed',
} as const

export interface BetEventDTOApi {
    /** Event payload as reported by the orchestrator. */
    payload: BetEventDTOApiPayload
    id: string
    bet_id: string
    kind: BetEventDTOKindEnumApi
    created_at: string
}

/**
 * Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}.
 */
export type CreateBetEventApiPayload = { [key: string]: unknown }

/**
 * * `run.started` - run.started
 * * `run.finished` - run.finished
 * * `node.spawned` - node.spawned
 * * `artifact.ready` - artifact.ready
 * * `gate.result` - gate.result
 * * `exposure.started` - exposure.started
 * * `verdict.proposed` - verdict.proposed
 * * `note` - note
 */
export type CreateBetEventKindEnumApi = (typeof CreateBetEventKindEnumApi)[keyof typeof CreateBetEventKindEnumApi]

export const CreateBetEventKindEnumApi = {
    Runstarted: 'run.started',
    Runfinished: 'run.finished',
    Nodespawned: 'node.spawned',
    Artifactready: 'artifact.ready',
    Gateresult: 'gate.result',
    Exposurestarted: 'exposure.started',
    Verdictproposed: 'verdict.proposed',
    Note: 'note',
} as const

export interface CreateBetEventApi {
    /** Typed event kind reported by the orchestrator. 'gate.result' with payload {pass: true} advances building → gated.
     *
     * * `run.started` - run.started
     * * `run.finished` - run.finished
     * * `node.spawned` - node.spawned
     * * `artifact.ready` - artifact.ready
     * * `gate.result` - gate.result
     * * `exposure.started` - exposure.started
     * * `verdict.proposed` - verdict.proposed
     * * `note` - note */
    kind: CreateBetEventKindEnumApi
    /** Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}. */
    payload?: CreateBetEventApiPayload
}

/**
 * * `promoted` - promoted
 * * `rolled_back` - rolled_back
 * * `iterate` - iterate
 */
export type RecordVerdictVerdictEnumApi = (typeof RecordVerdictVerdictEnumApi)[keyof typeof RecordVerdictVerdictEnumApi]

export const RecordVerdictVerdictEnumApi = {
    Promoted: 'promoted',
    RolledBack: 'rolled_back',
    Iterate: 'iterate',
} as const

export interface RecordVerdictApi {
    /** 'promoted' or 'rolled_back' archives the bet; 'iterate' sends it back to building with an incremented iteration counter.
     *
     * * `promoted` - promoted
     * * `rolled_back` - rolled_back
     * * `iterate` - iterate */
    verdict: RecordVerdictVerdictEnumApi
}
