import { randomUUID } from 'expo-crypto'

import { abortError } from '@/lib/abort'
import { isRecord } from '@/lib/records'
import { sleep } from '@/lib/sleep'

import type { BudgetFamily } from './budget'
import { apiJson, projectPath } from './client'
import { type ProjectScope, scopeKey } from './reports'

// Shapes follow `QueryRequest`, `QueryStatusResponse` and `TrendsQueryResponse` in `posthog/schema.py`.

/** `QueryStatus`. When `complete` is true, `results` holds the whole query response. */
export interface QueryStatusApi {
    id: string
    complete?: boolean | null
    error?: boolean | null
    error_message?: string | null
    results?: unknown
}

/** One series of a trends response. `days` holds the ISO bucket starts, aligned with `data`. */
export interface TrendsResultApi {
    data?: unknown
    days?: unknown
    labels?: unknown
    aggregated_value?: unknown
}

/** The web accepts both keys, so the app does too. */
export interface TrendsResponseApi {
    results?: TrendsResultApi[]
    result?: TrendsResultApi[]
}

export const QUERY_POLL_INTERVAL_MS = 1000
export const QUERY_POLL_TIMEOUT_MS = 30_000

export class QueryTimeoutError extends Error {
    constructor() {
        super('The query took too long. Try again later.')
        this.name = 'QueryTimeoutError'
    }
}

export class QueryFailedError extends Error {
    constructor(message: string | null | undefined) {
        super(message || 'The query failed.')
        this.name = 'QueryFailedError'
    }
}

function queryStatusOf(body: unknown): QueryStatusApi | undefined {
    const status = isRecord(body) ? body.query_status : undefined
    return isRecord(status) && typeof status.id === 'string' ? (status as unknown as QueryStatusApi) : undefined
}

/** `POST query/` has no cache-only read: the server turns a missing or `force_cache` value into `blocking`. */
export type QueryRefresh = 'blocking' | 'force_blocking'

export interface RunQueryOptions {
    signal?: AbortSignal
    pollIntervalMs?: number
    timeoutMs?: number
    refresh?: QueryRefresh
    /**
     * False returns a response that still carries a running `query_status` as it is, so the caller keeps its old
     * value instead of sending `GET query/{id}/` polls.
     */
    poll?: boolean
    /** Spends this budget instead of the Views `query` budget. */
    budgetFamily?: BudgetFamily
}

/**
 * `POST query/`, `blocking` unless told otherwise. The server answers inline for most queries; when it hands back a
 * running `query_status` instead, this polls `GET query/{id}/` until the status is complete.
 */
export async function runQuery(query: unknown, options: RunQueryOptions = {}): Promise<unknown> {
    const {
        signal,
        pollIntervalMs = QUERY_POLL_INTERVAL_MS,
        timeoutMs = QUERY_POLL_TIMEOUT_MS,
        refresh = 'blocking',
        poll = true,
        budgetFamily,
    } = options
    const deadline = Date.now() + timeoutMs
    const controller = new AbortController()
    let timedOut = false
    const abortFromCaller = (): void => controller.abort()
    signal?.addEventListener('abort', abortFromCaller, { once: true })
    if (signal?.aborted) {
        controller.abort()
    }
    const timer = setTimeout(
        () => {
            timedOut = true
            controller.abort()
        },
        Math.max(0, timeoutMs)
    )
    try {
        const body = await apiJson<unknown>(projectPath('query/'), {
            method: 'POST',
            json: { query, client_query_id: randomUUID(), refresh },
            signal: controller.signal,
            budgetFamily,
        })
        if (signal?.aborted) {
            throw abortError()
        }
        if (timedOut) {
            throw new QueryTimeoutError()
        }
        let status = queryStatusOf(body)
        if (!status || status.complete !== false || !poll) {
            if (status?.error) {
                throw new QueryFailedError(status.error_message)
            }
            return body
        }
        while (status.complete !== true) {
            if (Date.now() >= deadline) {
                throw new QueryTimeoutError()
            }
            await sleep(Math.min(pollIntervalMs, Math.max(0, deadline - Date.now())), controller.signal)
            const polled: unknown = await apiJson<unknown>(projectPath(`query/${encodeURIComponent(status.id)}/`), {
                signal: controller.signal,
                budgetFamily,
            })
            if (signal?.aborted) {
                throw abortError()
            }
            if (timedOut) {
                throw new QueryTimeoutError()
            }
            status = queryStatusOf(polled) ?? status
        }
        if (status.error) {
            throw new QueryFailedError(status.error_message)
        }
        return status.results
    } catch (error) {
        if (timedOut && !signal?.aborted) {
            throw new QueryTimeoutError()
        }
        throw error
    } finally {
        clearTimeout(timer)
        signal?.removeEventListener('abort', abortFromCaller)
    }
}

/** JSON with object keys sorted, so two equal queries give the same string whatever their key order. */
export function stableStringify(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map((item) => stableStringify(item ?? null)).join(',')}]`
    }
    if (isRecord(value)) {
        const entries = Object.keys(value)
            .sort()
            .filter((key) => value[key] !== undefined)
            .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
        return `{${entries.join(',')}}`
    }
    return JSON.stringify(value) ?? 'null'
}

export const queryKeys = {
    all: (scope: ProjectScope | null) => ['query', ...scopeKey(scope)] as const,
    run: (scope: ProjectScope | null, query: unknown) => [...queryKeys.all(scope), stableStringify(query)] as const,
}
