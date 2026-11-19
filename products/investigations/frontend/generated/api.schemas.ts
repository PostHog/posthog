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
 * * `investigating` - Investigating
 * * `review` - Review
 * * `monitoring` - Monitoring
 * * `closed` - Closed
 */
export type InvestigationStageEnumApi = (typeof InvestigationStageEnumApi)[keyof typeof InvestigationStageEnumApi]

export const InvestigationStageEnumApi = {
    Investigating: 'investigating',
    Review: 'review',
    Monitoring: 'monitoring',
    Closed: 'closed',
} as const

export interface InvestigationSummaryApi {
    /** Current investigation stage.
     *
     * * `investigating` - Investigating
     * * `review` - Review
     * * `monitoring` - Monitoring
     * * `closed` - Closed */
    status: InvestigationStageEnumApi
    /** Stable identifier for this investigation. */
    id: string
    /** The question this investigation answers. */
    question: string
    /** Current revision to pass with the next update. */
    revision: number
    /** Number of evidence queries and links. */
    evidence_count: number
    /** Number of retained result snapshots. */
    run_count: number
    /** When the investigation was last saved. */
    updated_at: string
    /** When the investigation was created. */
    created_at: string
    /**
     * ID of the creator, or null if the account was deleted.
     * @nullable
     */
    created_by: number | null
}

export interface InvestigationListApi {
    /** Investigations ordered by most recently updated first. */
    results: InvestigationSummaryApi[]
    /** Total number of matching investigations. */
    count: number
}

export type InvestigationStageApi = (typeof InvestigationStageApi)[keyof typeof InvestigationStageApi]

export const InvestigationStageApi = {
    Investigating: 'investigating',
    Review: 'review',
    Monitoring: 'monitoring',
    Closed: 'closed',
} as const

export type ChecksEnumApi = (typeof ChecksEnumApi)[keyof typeof ChecksEnumApi]

export const ChecksEnumApi = {
    Definition: 'definition',
    Maturity: 'maturity',
    Tracking: 'tracking',
    Population: 'population',
} as const

export type InvestigationEvidenceKindEnumApi =
    (typeof InvestigationEvidenceKindEnumApi)[keyof typeof InvestigationEvidenceKindEnumApi]

export const InvestigationEvidenceKindEnumApi = {
    Query: 'query',
    Link: 'link',
} as const

export interface InvestigationEvidenceApi {
    /**
     * @minLength 1
     * @maxLength 128
     */
    id: string
    /** @exclusiveMinimum 0 */
    reference: number
    /** @maxLength 200 */
    title: string
    kind: InvestigationEvidenceKindEnumApi
    /** @maxLength 10000 */
    sql: string
    /** @maxLength 2000 */
    url: string
    /** @maxLength 10000 */
    note: string
}

export type InvestigationHypothesisStatusApi =
    (typeof InvestigationHypothesisStatusApi)[keyof typeof InvestigationHypothesisStatusApi]

export const InvestigationHypothesisStatusApi = {
    Open: 'open',
    Supported: 'supported',
    RuledOut: 'ruled_out',
} as const

export interface InvestigationHypothesisApi {
    /**
     * @minLength 1
     * @maxLength 128
     */
    id: string
    /** @maxLength 500 */
    title: string
    status: InvestigationHypothesisStatusApi
    /** @maxLength 10000 */
    reasoning: string
    /**
     * @maxItems 12
     * @items.minLength 1
     * @items.maxLength 128
     */
    evidenceIds: string[]
}

export interface InvestigationEvidenceResultApi {
    /**
     * @minLength 1
     * @maxLength 128
     */
    evidenceId: string
    /** @maxLength 200 */
    title: string
    /** @maxLength 10000 */
    sql: string
    /**
     * @maxItems 20
     * @items.maxLength 500
     */
    columns: string[]
    /**
     * @maxItems 50
     * @items.maxItems 20
     */
    rows: (string | number | boolean | null)[][]
    truncated: boolean
    error: string | null
}

export interface InvestigationRunApi {
    /**
     * @minLength 1
     * @maxLength 128
     */
    id: string
    at: string
    /** @maxLength 10000 */
    conclusion: string
    /** @maxItems 12 */
    results: InvestigationEvidenceResultApi[]
}

export interface InvestigationDocumentApi {
    version: 1
    /** @maxLength 500 */
    question: string
    status: InvestigationStageApi
    /** @maxLength 10000 */
    context: string
    /** @maxItems 4 */
    checks: ChecksEnumApi[]
    /** @maxItems 12 */
    evidence: InvestigationEvidenceApi[]
    /** @exclusiveMinimum 0 */
    nextEvidenceNumber: number
    /** @maxItems 12 */
    hypotheses: InvestigationHypothesisApi[]
    /** @maxLength 10000 */
    conclusion: string
    /** @maxLength 10000 */
    decision: string
    /** @maxLength 2000 */
    followUp: string
    /** @maxItems 10 */
    runs: InvestigationRunApi[]
    baselineId: string | null
    example: boolean
}

export interface InvestigationCreateApi {
    /** The investigation document to save. Version must be 1. */
    document: InvestigationDocumentApi
}

export interface SavedInvestigationApi {
    /** Current investigation stage.
     *
     * * `investigating` - Investigating
     * * `review` - Review
     * * `monitoring` - Monitoring
     * * `closed` - Closed */
    status: InvestigationStageEnumApi
    /** Question, evidence, hypotheses, decisions, and bounded result snapshots. */
    document: InvestigationDocumentApi
    /** Stable identifier for this investigation. */
    id: string
    /** The question this investigation answers. */
    question: string
    /** Current revision to pass with the next update. */
    revision: number
    /** Number of evidence queries and links. */
    evidence_count: number
    /** Number of retained result snapshots. */
    run_count: number
    /** When the investigation was last saved. */
    updated_at: string
    /** When the investigation was created. */
    created_at: string
    /**
     * ID of the creator, or null if the account was deleted.
     * @nullable
     */
    created_by: number | null
}

export interface InvestigationErrorApi {
    /** What prevented the operation and how to recover. */
    detail: string
}

export interface PatchedInvestigationUpdateApi {
    /**
     * Last read revision. Stale writes are rejected with HTTP 409.
     * @minimum 1
     */
    revision?: number
    /** Replacement document, preserving existing evidence and run IDs. */
    document?: InvestigationDocumentApi
    /** Archive this investigation and remove it from the list. */
    deleted?: boolean
}

export type InvestigationsListParams = {
    /**
     * Maximum number of investigations to return.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Number of investigations to skip.
     * @minimum 0
     */
    offset?: number
    /**
     * Search the investigation question.
     * @minLength 1
     * @maxLength 500
     */
    search?: string
}
