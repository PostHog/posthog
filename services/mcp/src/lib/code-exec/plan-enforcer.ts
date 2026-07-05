/**
 * Apply-mode transport. Reads pass through; every attempted mutation must match
 * a not-yet-consumed plan entry on (method, normalized path, normalized body)
 * *after* substituting `$planRef` bindings with the real values captured from
 * earlier applied mutations' actual responses. A mutation with no match aborts
 * the run with a typed `PlanDivergenceError` and poisons the transport, so every
 * later call — read or write — fails fast.
 */

import type { Classifier } from './classifier'
import { deepEqualCanonical, substituteRefsInBody, substituteRefsInPath } from './hashes'
import { extractHttpRequest } from './plan-recorder'
import type { AttemptedCall, FetchLike, MutationOutcome, NormalizedMutation, Plan } from './types'

export class PlanDivergenceError extends Error {
    readonly kind = 'plan_divergence'
    readonly attempted: AttemptedCall
    readonly closestPlanEntry: NormalizedMutation | null

    constructor(attempted: AttemptedCall, closestPlanEntry: NormalizedMutation | null) {
        super(
            `Apply diverged from the confirmed plan: ${attempted.method} ${attempted.path} was not an unconsumed planned mutation. Re-plan and confirm the new plan.`
        )
        this.name = 'PlanDivergenceError'
        this.attempted = attempted
        this.closestPlanEntry = closestPlanEntry
    }
}

export interface EnforceTransportOptions {
    realFetch: FetchLike
    plan: Plan
    /**
     * Reads (including `POST /query/`) must pass through in enforce mode too, so
     * the classifier is required to tell reads from mutations — the plan alone
     * cannot distinguish a read from a divergent mutation.
     */
    classifier: Classifier
}

export interface EnforceTransport {
    fetch: FetchLike
    getReceipt(): MutationOutcome[]
}

export function createEnforceTransport(options: EnforceTransportOptions): EnforceTransport {
    const { realFetch, plan, classifier } = options
    const consumed: boolean[] = Array.from({ length: plan.normalizedMutations.length }, () => false)
    const bindings = new Map<string, string | number>()
    const outcomes = new Map<number, MutationOutcome>()
    let poison: PlanDivergenceError | null = null

    const fetch: FetchLike = async (input, init) => {
        if (poison) {
            throw poison
        }
        const { method, path, body } = extractHttpRequest(input, init)
        const classification = classifier.classify(method, path, body)
        if (classification.kind === 'read') {
            return realFetch(input, init)
        }

        const attempted: AttemptedCall = { method, path, body }
        const matchIndex = findMatch(plan.normalizedMutations, consumed, bindings, attempted)
        if (matchIndex === -1) {
            poison = new PlanDivergenceError(attempted, closestUnconsumed(plan.normalizedMutations, consumed, method))
            throw poison
        }

        consumed[matchIndex] = true
        const entry = plan.normalizedMutations[matchIndex]!
        return forwardAndCapture(realFetch, input, init, entry, attempted, plan, bindings, outcomes)
    }

    const getReceipt = (): MutationOutcome[] =>
        plan.normalizedMutations.map(
            (entry) =>
                outcomes.get(entry.sequence) ?? {
                    sequence: entry.sequence,
                    operationId: entry.operationId,
                    method: entry.method,
                    path: substituteRefsInPath(entry.path, bindings),
                    status: 'skipped',
                }
        )

    return { fetch, getReceipt }
}

function findMatch(
    entries: NormalizedMutation[],
    consumed: boolean[],
    bindings: Map<string, string | number>,
    attempted: AttemptedCall
): number {
    for (let i = 0; i < entries.length; i++) {
        if (consumed[i]) {
            continue
        }
        const entry = entries[i]!
        if (entry.method !== attempted.method) {
            continue
        }
        const expectedPath = substituteRefsInPath(entry.path, bindings)
        if (expectedPath !== attempted.path) {
            continue
        }
        const expectedBody = substituteRefsInBody(entry.body, bindings)
        if (deepEqualCanonical(expectedBody, attempted.body)) {
            return i
        }
    }
    return -1
}

function closestUnconsumed(
    entries: NormalizedMutation[],
    consumed: boolean[],
    method: string
): NormalizedMutation | null {
    let firstUnconsumed: NormalizedMutation | null = null
    for (let i = 0; i < entries.length; i++) {
        if (consumed[i]) {
            continue
        }
        const entry = entries[i]!
        if (firstUnconsumed === null) {
            firstUnconsumed = entry
        }
        if (entry.method === method) {
            return entry
        }
    }
    return firstUnconsumed
}

async function forwardAndCapture(
    realFetch: FetchLike,
    input: string | URL | Request,
    init: RequestInit | undefined,
    entry: NormalizedMutation,
    attempted: AttemptedCall,
    plan: Plan,
    bindings: Map<string, string | number>,
    outcomes: Map<number, MutationOutcome>
): Promise<Response> {
    const response = await realFetch(input, init)

    let responseBody: unknown
    try {
        responseBody = await response.clone().json()
    } catch {
        responseBody = undefined
    }

    if (response.ok) {
        captureBindings(entry.sequence, plan, responseBody, bindings)
    }

    outcomes.set(entry.sequence, {
        sequence: entry.sequence,
        operationId: entry.operationId,
        method: entry.method,
        path: attempted.path,
        status: response.ok ? 'applied' : 'failed',
        response: responseBody,
        error: response.ok ? undefined : `HTTP ${response.status}`,
    })

    return response
}

/** Bind each sentinel field of the recorded mutation to the real response value. */
function captureBindings(
    sequence: number,
    plan: Plan,
    responseBody: unknown,
    bindings: Map<string, string | number>
): void {
    if (typeof responseBody !== 'object' || responseBody === null) {
        return
    }
    const recorded = plan.mutations[sequence]
    if (!recorded) {
        return
    }
    const record = responseBody as Record<string, unknown>
    for (const sentinel of recorded.sentinels) {
        const real = record[sentinel.field]
        if (typeof real === 'string' || typeof real === 'number') {
            bindings.set(`${sequence}:${sentinel.field}`, real)
        }
    }
}
