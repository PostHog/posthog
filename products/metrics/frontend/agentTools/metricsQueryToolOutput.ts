import { asRecord, getToolOutputRecord } from 'products/posthog_ai/frontend/api/tools'
import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

export interface MetricSeriesSummary {
    /** What the series is: the metric name, or the formula's clause alias when a formula ran. */
    name: string
    /** The label values the series was split by, as `key=value` pairs. */
    labels: string[]
    /** Null where the API reported no representable aggregate for the bucket — a gap, not a zero. */
    values: (number | null)[]
    times: string[]
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function asNullableNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function seriesLabels(labels: unknown): string[] {
    const record = asRecord(labels)
    return record ? Object.entries(record).map(([key, value]) => `${key}=${String(value)}`) : []
}

/**
 * Pull the returned series out of a `query-metrics` tool result. Returns an array (possibly empty
 * when the query matched nothing) or null when the output has no `results` array to render — in
 * which case the widget falls back to the generic card rather than showing an empty chart panel.
 */
export function extractMetricSeries(message: ToolCallMessage): MetricSeriesSummary[] | null {
    const output = getToolOutputRecord(message)
    const results = output?.results
    if (!Array.isArray(results)) {
        return null
    }
    return results
        .map((series) => asRecord(series))
        .filter((series): series is Record<string, unknown> => series !== null)
        .map((series) => {
            const points = Array.isArray(series.points) ? series.points.map((point) => asRecord(point)) : []
            return {
                name: asString(series.metric_name) || asString(series.clause) || 'Series',
                labels: seriesLabels(series.labels),
                values: points.map((point) => asNullableNumber(point?.value)),
                times: points.map((point) => asString(point?.time)),
            }
        })
}

/**
 * A one-line summary of what the query-metrics call asked for, drawn from the tool's own input args,
 * for the card subtitle. The args are raw agent JSON, so every field is read defensively.
 */
export function describeMetricsQuery(message: ToolCallMessage): string | undefined {
    const input = asRecord(message.innerInput)
    const query = asRecord(input?.query) ?? input
    if (!query) {
        return undefined
    }

    const clauses = Array.isArray(query.clauses) ? query.clauses.map((clause) => asRecord(clause)) : []
    const metricNames = clauses.length
        ? clauses.map((clause) => asString(clause?.metricName)).filter(Boolean)
        : [asString(query.metricName)].filter(Boolean)
    const aggregation = asString(clauses[0]?.aggregation) || asString(query.aggregation)
    const formula = asString(query.formula)
    const dateFrom = asString(query.dateFrom)

    const parts = [
        metricNames.join(', '),
        aggregation,
        formula ? `formula: ${formula}` : '',
        dateFrom ? `from ${dateFrom}` : '',
    ].filter(Boolean)

    return parts.length > 0 ? parts.join(' · ') : undefined
}
