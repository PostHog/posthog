/**
 * Ranks governed-metrics catalog rows for `exec search` (src/tools/exec.ts).
 *
 * A metric question ("what's our ARR?") should surface the governed metric next
 * to the tool matches, so the agent runs `data-catalog-metric-run` instead of
 * searching insights or deriving with SQL. This reuses the same field-weighted
 * token ranking as tool search by projecting each metric onto `SearchableTool`
 * (`display_name` → `title`), so a metric name hit outranks a description hit.
 */

import type { CatalogMetricSummary } from '@/api/client'

import { searchToolsRanked } from './tool-search'

/** A governed-metric hit returned in the `exec search` result. Carries `status`
 *  and `is_drifted` so the model still applies the trust rules — only an
 *  `approved`, non-drifted metric is canonical. */
export interface GovernedMetricMatch {
    name: string
    display_name: string
    description: string
    status: string
    is_drifted: boolean
}

const MAX_METRIC_SEARCH_RESULTS = 5

export function searchCatalogMetrics(
    metrics: readonly CatalogMetricSummary[],
    query: string,
    limit: number = MAX_METRIC_SEARCH_RESULTS
): GovernedMetricMatch[] {
    const searchable = metrics.map((m) => ({
        name: m.name,
        title: m.display_name ?? '',
        description: m.description ?? '',
    }))
    const byName = new Map(metrics.map((m) => [m.name, m]))
    return searchToolsRanked(searchable, query)
        .slice(0, limit)
        .map((match) => byName.get(match.name))
        .filter((m): m is CatalogMetricSummary => m !== undefined)
        .map((m) => ({
            name: m.name,
            display_name: m.display_name,
            description: m.description,
            status: m.status,
            is_drifted: m.is_drifted,
        }))
}
