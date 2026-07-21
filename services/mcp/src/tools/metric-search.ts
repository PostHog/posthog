import type { ApiClient } from '@/api/client'
import type { Schemas } from '@/api/generated'
import { PostHogApiError } from '@/lib/errors'
import type { StateManager } from '@/lib/StateManager'

import { isRegexPattern, searchToolsRanked, searchToolsRegex } from './tool-search'

/**
 * Governed-metric lookup for `exec search` (src/tools/exec.ts).
 *
 * Fetches the team's data-catalog metrics through the authenticated REST list
 * endpoint and ranks them with the same field-weighted search used for tools,
 * so a keyword query like "revenue" surfaces a governed metric alongside tool
 * matches. Search must never degrade because of the catalog: every failure —
 * HTTP error, missing scope, invalid regex, timeout — resolves to `[]`.
 */

export interface GovernedMetricMatch {
    name: string
    display_name: string
    description: string
    status: string
    is_drifted: boolean
}

export type GovernedMetricsSearcher = (query: string) => Promise<GovernedMetricMatch[]>

export interface MetricSearchOutcome {
    status: 'ok' | 'timeout' | 'error'
    durationMs: number
    /** Value-free failure category for telemetry: `http_<status>` or the error name. */
    failureClass?: string
}

export interface MetricSearchOptions {
    timeoutMs?: number
    onOutcome?: (outcome: MetricSearchOutcome) => void
}

/** Structural slice of `Context` the searcher needs — keeps tests light and the
 *  dependency direction hook-shaped (exec.ts never learns about the API client). */
export interface MetricSearchDeps {
    stateManager: Pick<StateManager, 'getProjectId'>
    api: Pick<ApiClient, 'request'>
}

export const MAX_METRIC_SEARCH_RESULTS = 5
const DESCRIPTION_TRUNCATE_CHARS = 200
const DEFAULT_TIMEOUT_MS = 2_000
// The list endpoint returns a DRF LimitOffset envelope with a default page of
// 100 — an explicit high limit keeps ranking over the whole catalog instead of
// silently missing older metrics.
const METRICS_FETCH_LIMIT = 500

class MetricFetchTimeoutError extends Error {
    constructor(timeoutMs: number) {
        super(`Governed-metrics fetch exceeded ${timeoutMs}ms`)
        this.name = 'MetricFetchTimeoutError'
    }
}

interface SearchableMetric {
    name: string
    title: string
    description: string
    metric: Schemas.DataCatalogMetric
}

function toSearchable(metric: Schemas.DataCatalogMetric): SearchableMetric {
    return {
        name: metric.name,
        title: metric.display_name ?? '',
        description: metric.description ?? '',
        metric,
    }
}

function toMatch(metric: Schemas.DataCatalogMetric): GovernedMetricMatch {
    const description = metric.description ?? ''
    return {
        name: metric.name,
        display_name: metric.display_name ?? '',
        description:
            description.length > DESCRIPTION_TRUNCATE_CHARS
                ? `${description.slice(0, DESCRIPTION_TRUNCATE_CHARS)}…`
                : description,
        status: metric.status,
        is_drifted: metric.is_drifted,
    }
}

function rankMetrics(metrics: Schemas.DataCatalogMetric[], query: string): GovernedMetricMatch[] {
    const searchables = metrics.map(toSearchable)
    if (isRegexPattern(query)) {
        return searchToolsRegex(searchables, query)
            .slice(0, MAX_METRIC_SEARCH_RESULTS)
            .map((s) => toMatch(s.metric))
    }
    const byName = new Map(searchables.map((s) => [s.name, s.metric]))
    return searchToolsRanked(searchables, query)
        .slice(0, MAX_METRIC_SEARCH_RESULTS)
        .map((ranked) => byName.get(ranked.name))
        .filter((m): m is Schemas.DataCatalogMetric => m !== undefined)
        .map(toMatch)
}

async function fetchMetrics(deps: MetricSearchDeps, signal: AbortSignal): Promise<Schemas.DataCatalogMetric[]> {
    const projectId = await deps.stateManager.getProjectId()
    const response = await deps.api.request<Schemas.PaginatedDataCatalogMetricList>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/metrics/`,
        query: { limit: METRICS_FETCH_LIMIT },
        signal,
    })
    return response.results ?? []
}

// The race supplies the typed timeout error the moment the bound elapses;
// `onTimeout` aborts the outbound request so a hung endpoint doesn't keep
// paying network cost after the result was already discarded.
function withTimeout<T>(promise: Promise<T>, timeoutMs: number, onTimeout: () => void): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const timer = setTimeout(() => {
            onTimeout()
            reject(new MetricFetchTimeoutError(timeoutMs))
        }, timeoutMs)
        promise
            .then((value) => resolve(value))
            .catch((error) => reject(error))
            .finally(() => clearTimeout(timer))
    })
}

function classifyFailure(error: unknown): string {
    if (error instanceof MetricFetchTimeoutError) {
        return 'timeout'
    }
    if (error instanceof PostHogApiError) {
        return `http_${error.status}`
    }
    return error instanceof Error ? error.name : 'unknown'
}

export function createGovernedMetricsSearcher(
    deps: MetricSearchDeps,
    options: MetricSearchOptions = {}
): GovernedMetricsSearcher {
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
    return async (query: string): Promise<GovernedMetricMatch[]> => {
        const startMs = Date.now()
        const controller = new AbortController()
        try {
            const metrics = await withTimeout(fetchMetrics(deps, controller.signal), timeoutMs, () =>
                controller.abort()
            )
            const matches = rankMetrics(metrics, query)
            options.onOutcome?.({ status: 'ok', durationMs: Date.now() - startMs })
            return matches
        } catch (error) {
            options.onOutcome?.({
                status: error instanceof MetricFetchTimeoutError ? 'timeout' : 'error',
                durationMs: Date.now() - startMs,
                failureClass: classifyFailure(error),
            })
            return []
        }
    }
}
