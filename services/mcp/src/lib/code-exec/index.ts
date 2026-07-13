/**
 * Public surface of the plan/apply (Terraform-style dry-run) engine.
 *
 * The engine is pure server-side and HTTP-level: it never imports the SDK. The
 * plan recorder and apply enforcer are WHATWG `fetch` implementations wrapping a
 * real `fetch`, handed to the SDK later via `createClient({ fetch })`.
 */

export type {
    AttemptedCall,
    Classification,
    ClassifierOperation,
    ClassifierTable,
    FetchLike,
    IdField,
    MutationOutcome,
    NormalizedMutation,
    Plan,
    PlanRef,
    PlanRunResult,
    RecordedMutation,
    SentinelAssignment,
} from './types'
export { isPlanRef } from './types'

export type { Classifier } from './classifier'
export { createClassifier } from './classifier'

export type { SentinelFactory } from './sentinels'
export { createSentinelFactory, findSentinelRefs } from './sentinels'

export type { IssuedSentinel } from './hashes'
export {
    computePlanHash,
    computeScriptHash,
    deepEqualCanonical,
    normalizePath,
    normalizeValue,
    sha256Hex,
    stableStringify,
    substituteRefsInBody,
    substituteRefsInPath,
} from './hashes'

export type { BuildPlanOptions, HttpRequestParts, PlanTransport, PlanTransportOptions } from './plan-recorder'
export { buildPlan, createPlanTransport, extractHttpRequest } from './plan-recorder'

export type { EnforceTransport, EnforceTransportOptions } from './plan-enforcer'
export { createEnforceTransport, PlanDivergenceError } from './plan-enforcer'

export type { CurrentObjects } from './plan-render'
export { renderPlanText, renderReceiptText } from './plan-render'

export { generatePlanPhrase, normalizePlanPhrase, PLAN_PHRASE_TTL_SECONDS, PLAN_PHRASE_WORD_COUNT } from './plan-phrase'

export type {
    MemoryPlanStoreOptions,
    PlanStore,
    PlanStoreRedis,
    RedisPlanStoreOptions,
    StoredCallPlan,
    StoredPlan,
    StoredScriptPlan,
} from './plan-store'
export { MemoryPlanStore, RedisPlanStore } from './plan-store'

export type { FilePlanStoreOptions } from './file-plan-store'
export { FilePlanStore } from './file-plan-store'
