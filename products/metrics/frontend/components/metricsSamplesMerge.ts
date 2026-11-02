import type { _MetricEventSampleApi, _MetricSamplesBodyApi } from 'products/metrics/frontend/generated/api.schemas'

import { type MetricsViewerClause, metricFiltersForGroup } from './metricsViewerLogic'

/** A raw emission, with the aliases of the series whose query returned it. */
export type MetricsSampleRow = _MetricEventSampleApi & { clauses: string[] }

/** One samples request without its date range, and the series that share it. */
export interface MetricsSampleRequest {
    query: Omit<_MetricSamplesBodyApi, 'dateFrom' | 'dateTo' | 'limit'>
    clauses: string[]
}

/** One request per distinct series query. Series with the same metric, type and filters share a request. */
export function buildSampleRequests(namedClauses: MetricsViewerClause[]): MetricsSampleRequest[] {
    const requests = new Map<string, MetricsSampleRequest>()
    for (const clause of namedClauses) {
        const filters = metricFiltersForGroup(clause.filterGroup)
        const query: MetricsSampleRequest['query'] = {
            metricName: clause.metricName.trim(),
            ...(clause.selectedMetricType ? { metricType: clause.selectedMetricType } : {}),
            ...(filters.length ? { filters } : {}),
        }
        const key = JSON.stringify(query)
        const existing = requests.get(key)
        if (existing) {
            existing.clauses.push(clause.name)
        } else {
            requests.set(key, { query, clauses: [clause.name] })
        }
    }
    return [...requests.values()]
}

const sampleTime = (sample: _MetricEventSampleApi): number => Date.parse(sample.timestamp)

// Overlapping series (one adds a filter to the other) return the same emission, so it is keyed by content.
const sampleIdentity = (sample: _MetricEventSampleApi): string =>
    JSON.stringify([
        sample.metric_name,
        sampleTime(sample),
        sample.value,
        sample.count,
        sample.service_name,
        sample.trace_id,
        sample.span_id,
        sample.attributes,
        sample.resource_attributes,
    ])

/**
 * Merges the samples of each request into at most `limit` rows, newest first.
 * Each request first gets an equal share of the rows, so a busy series cannot push a quiet one out.
 * Rows that a share leaves unused go to the newest remaining samples.
 */
export function mergeSamples(
    results: { clauses: string[]; samples: _MetricEventSampleApi[] }[],
    limit: number
): MetricsSampleRow[] {
    const rows = new Map<string, MetricsSampleRow>()
    const keysPerRequest = results.map(({ clauses, samples }) => {
        // Repeats inside one response stay separate rows. Only the same occurrence across responses merges.
        const occurrences = new Map<string, number>()
        return [...samples]
            .sort((left, right) => sampleTime(right) - sampleTime(left))
            .map((sample) => {
                const identity = sampleIdentity(sample)
                const occurrence = occurrences.get(identity) ?? 0
                occurrences.set(identity, occurrence + 1)
                const key = `${identity}#${occurrence}`
                const row = rows.get(key)
                if (row) {
                    row.clauses = [...new Set([...row.clauses, ...clauses])]
                } else {
                    rows.set(key, { ...sample, clauses: [...clauses] })
                }
                return key
            })
    })

    const picked = new Set<string>()
    const share = Math.ceil(limit / Math.max(results.length, 1))
    for (const keys of keysPerRequest) {
        let taken = 0
        for (const key of keys) {
            if (taken >= share || picked.size >= limit) {
                break
            }
            if (!picked.has(key)) {
                picked.add(key)
                taken++
            }
        }
    }
    const newestFirst = [...rows.entries()].sort(([, left], [, right]) => sampleTime(right) - sampleTime(left))
    for (const [key] of newestFirst) {
        if (picked.size >= limit) {
            break
        }
        picked.add(key)
    }
    return newestFirst.filter(([key]) => picked.has(key)).map(([, row]) => row)
}
