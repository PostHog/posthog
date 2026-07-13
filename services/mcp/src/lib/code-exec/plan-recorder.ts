/**
 * Plan-mode transport. Reads pass through to the real `fetch` untouched;
 * classified mutations — and unclassified non-reads (fail closed) — are
 * recorded and answered with a *synthetic* response so the script keeps running
 * without any mutation reaching the API. The synthetic response echoes the
 * request body and adds schema-correct sentinel values for the operation's
 * identifier fields (plus `deleted: true` for soft deletes).
 */

import type { Classifier } from './classifier'
import { computePlanHash, computeScriptHash, type IssuedSentinel, normalizePath, normalizeValue } from './hashes'
import type { SentinelFactory } from './sentinels'
import type { FetchLike, IdField, NormalizedMutation, Plan, RecordedMutation, SentinelAssignment } from './types'

/** Default identifier field when the classifier can't tell us (fail-closed). */
const DEFAULT_ID_FIELD: IdField = { name: 'id', type: 'number' }

export interface PlanTransportOptions {
    realFetch: FetchLike
    classifier: Classifier
    sentinels: SentinelFactory
}

export interface PlanTransport {
    fetch: FetchLike
    getMutations(): RecordedMutation[]
}

export interface HttpRequestParts {
    method: string
    /** Pathname plus query string. */
    path: string
    body: unknown
}

/**
 * Extract method/path/body from a WHATWG fetch call. The SDK issues calls as
 * `(url, init)` with a string body, which is all this layer needs; a `Request`
 * input is handled for completeness (its body, if any, is not read here).
 */
export function extractHttpRequest(input: string | URL | Request, init?: RequestInit): HttpRequestParts {
    const isRequest = typeof Request !== 'undefined' && input instanceof Request
    const method = (init?.method ?? (isRequest ? (input as Request).method : 'GET')).toUpperCase()
    const url = isRequest ? (input as Request).url : input instanceof URL ? input.toString() : String(input)

    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        parsed = new URL(url, 'http://placeholder')
    }
    const path = parsed.pathname + parsed.search

    const rawBody = typeof init?.body === 'string' ? init.body : null
    let body: unknown
    if (rawBody !== null) {
        try {
            body = JSON.parse(rawBody)
        } catch {
            body = rawBody
        }
    }
    return { method, path, body }
}

export function createPlanTransport(options: PlanTransportOptions): PlanTransport {
    const { realFetch, classifier, sentinels } = options
    const mutations: RecordedMutation[] = []

    const fetch: FetchLike = async (input, init) => {
        const { method, path, body } = extractHttpRequest(input, init)
        const classification = classifier.classify(method, path, body)
        if (classification.kind === 'read') {
            return realFetch(input, init)
        }

        const sequence = mutations.length
        const operation = classification.operation
        const idFields = operation?.idFields.length ? operation.idFields : [DEFAULT_ID_FIELD]
        // A soft-delete-capable operation shares its wire shape with a plain
        // update (both PATCH the same path); only a body that sets `deleted:true`
        // is actually a delete.
        const softDelete = (operation?.softDelete ?? false) && bodyMarksDeleted(body)

        const assignments: SentinelAssignment[] = idFields.map((field) => sentinels.issue(sequence, field))

        mutations.push({
            sequence,
            operationId: classification.operationId,
            method,
            path,
            body,
            softDelete,
            destructive: operation?.destructive ?? false,
            objectType: operation?.objectType ?? null,
            sentinels: assignments,
        })

        return synthesizeResponse(method, body, assignments, softDelete)
    }

    return { fetch, getMutations: () => [...mutations] }
}

function bodyMarksDeleted(body: unknown): boolean {
    return (
        typeof body === 'object' &&
        body !== null &&
        !Array.isArray(body) &&
        (body as Record<string, unknown>).deleted === true
    )
}

function synthesizeResponse(
    method: string,
    body: unknown,
    assignments: SentinelAssignment[],
    softDelete: boolean
): Response {
    const echo: Record<string, unknown> =
        typeof body === 'object' && body !== null && !Array.isArray(body)
            ? { ...(body as Record<string, unknown>) }
            : {}
    for (const assignment of assignments) {
        echo[assignment.field] = assignment.value
    }
    if (softDelete) {
        echo.deleted = true
    }
    const status = method === 'POST' ? 201 : 200
    return new Response(JSON.stringify(echo), {
        status,
        headers: { 'content-type': 'application/json' },
    })
}

export interface BuildPlanOptions {
    now?: () => number
}

/**
 * Assemble recorded mutations into a `Plan`: normalize each mutation (replacing
 * sentinel occurrences with `$planRef` markers), then hash. Sentinels are
 * globally unique across the execution, so a value appearing in a later
 * mutation can only be one issued earlier — a global scan is sound.
 */
export function buildPlan(mutations: RecordedMutation[], script: string, options: BuildPlanOptions = {}): Plan {
    const sentinels: IssuedSentinel[] = mutations.flatMap((mutation) =>
        mutation.sentinels.map((sentinel) => ({
            sequence: mutation.sequence,
            field: sentinel.field,
            value: sentinel.value,
        }))
    )

    const normalizedMutations: NormalizedMutation[] = mutations.map((mutation) => ({
        sequence: mutation.sequence,
        operationId: mutation.operationId,
        method: mutation.method,
        path: normalizePath(mutation.path, sentinels),
        body: normalizeValue(mutation.body, sentinels),
    }))

    return {
        mutations,
        normalizedMutations,
        planHash: computePlanHash(normalizedMutations),
        scriptHash: computeScriptHash(script),
        createdAt: options.now ? options.now() : Date.now(),
    }
}
