import { formatRelativeAgo } from '@/lib/dates'
import { formatMetricValue } from '@/model/adapters/metric'
import type { MetricView, QueryState } from '@/model/types'

/**
 * `live`: the server's value for the window. `saved`: the snapshot, with the time it was measured. `failed` is true
 * when the live query errored. `missing`: no live value and no snapshot.
 */
export type MetricValueState =
    | { kind: 'loading' }
    | { kind: 'live'; text: string }
    | { kind: 'saved'; text: string; measured?: string; failed: boolean }
    | { kind: 'missing'; failed: boolean; retry: () => unknown }

export const MISSING_VALUE = 'Not available'

function measuredLabel(at: string | null, now: Date): string | undefined {
    if (!at || !Number.isFinite(Date.parse(at))) {
        return undefined
    }
    const ago = formatRelativeAgo(at, now)
    return `Measured ${ago === 'Just now' ? 'just now' : ago}`
}

export function metricValueState(
    aggregate: QueryState<number>,
    metric: Pick<MetricView, 'format' | 'snapshot'>,
    now: Date
): MetricValueState {
    const format = (value: number): string => formatMetricValue(value, metric.format.valueFormat, metric.format.unit)
    if (aggregate.data !== undefined) {
        return { kind: 'live', text: format(aggregate.data) }
    }
    const snapshot = metric.snapshot
    if (snapshot) {
        const measured = measuredLabel(snapshot.at, now)
        return {
            kind: 'saved',
            text: format(snapshot.value),
            ...(measured ? { measured } : {}),
            failed: aggregate.isError,
        }
    }
    if (aggregate.isLoading) {
        return { kind: 'loading' }
    }
    return { kind: 'missing', failed: aggregate.isError, retry: aggregate.refetch }
}
