/**
 * Shared types for the plan/apply (Terraform-style dry-run) engine.
 *
 * The engine sits at the HTTP transport seam: both the plan recorder and the
 * apply enforcer are WHATWG `fetch` implementations wrapping a real `fetch`,
 * handed to the SDK later via `createClient({ fetch })`. Nothing here imports
 * the SDK — this layer only ever sees raw HTTP.
 */

/** WHATWG fetch — the exact shape the SDK accepts as an injectable transport. */
export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>

/** An identifier field on a response, used to synthesize schema-correct sentinels. */
export interface IdField {
    name: string
    type: 'number' | 'string'
}

/**
 * One classifier entry — mirrors the generated `classifier-table.json` operation
 * shape exactly, so the generated artifact deserializes straight into this type.
 */
export interface ClassifierOperation {
    id: string
    method: string
    pathTemplate: string
    pathAliases: string[]
    readOnly: boolean
    destructive: boolean
    softDelete: boolean
    objectType: string
    displayNameFields: string[]
    scopes: string[]
    idFields: IdField[]
}

export interface ClassifierTable {
    version: number
    operations: ClassifierOperation[]
}

export interface Classification {
    kind: 'read' | 'mutation'
    /** Classifier match; `null` when unmatched (a fail-closed mutation). */
    operationId: string | null
    /** The matched table entry, or `null` when unmatched. */
    operation: ClassifierOperation | null
}

/** A sentinel value issued in a synthetic plan-mode response. */
export interface SentinelAssignment {
    field: string
    value: string | number
}

/** A mutation intercepted and recorded during the plan pass, raw form. */
export interface RecordedMutation {
    /** 0-based, order of interception. */
    sequence: number
    /** Classifier match; `null` = unclassified (fail-closed mutation). */
    operationId: string | null
    method: string
    /** Concrete path (with query) exactly as requested. */
    path: string
    /** Parsed JSON body, or the raw string when unparseable. */
    body: unknown
    softDelete: boolean
    destructive: boolean
    objectType: string | null
    /** Sentinels issued in this mutation's synthetic response. */
    sentinels: SentinelAssignment[]
}

/** Reference marker standing in for a sentinel value in the normalized plan. */
export interface PlanRef {
    $planRef: { sequence: number; field: string }
}

/**
 * A mutation in normalized form: sentinel occurrences in path/body replaced by
 * `$planRef` markers. This is what the plan hash is computed over and what the
 * enforcer matches attempted calls against (after binding substitution).
 */
export interface NormalizedMutation {
    sequence: number
    operationId: string | null
    method: string
    path: string
    body: unknown
}

export interface Plan {
    /** Raw recorded mutations, kept for display/rendering. */
    mutations: RecordedMutation[]
    /** Normalized mutations with `$planRef` bindings, for hashing + enforcement. */
    normalizedMutations: NormalizedMutation[]
    /** sha256 over the normalized mutation list with stable key ordering. */
    planHash: string
    /** sha256 of the exact script source. */
    scriptHash: string
    createdAt: number
}

export interface PlanRunResult {
    kind: 'no-mutations' | 'plan'
    /** Script `export default` value (provisional when kind === 'plan'). */
    output: unknown
    consoleOutput: string[]
    plan?: Plan
}

/** A mutation the apply pass attempted, as seen at the transport. */
export interface AttemptedCall {
    method: string
    path: string
    body: unknown
}

/** Per-mutation outcome reported by the enforcer after an apply pass. */
export interface MutationOutcome {
    sequence: number
    operationId: string | null
    method: string
    path: string
    status: 'applied' | 'failed' | 'skipped'
    /** Real response body for applied/failed mutations. */
    response?: unknown
    error?: string
}

export function isPlanRef(value: unknown): value is PlanRef {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const ref = (value as { $planRef?: unknown }).$planRef
    return (
        typeof ref === 'object' &&
        ref !== null &&
        typeof (ref as { sequence?: unknown }).sequence === 'number' &&
        typeof (ref as { field?: unknown }).field === 'string'
    )
}
