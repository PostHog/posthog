import { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { WebOverviewItem } from '~/queries/schema/schema-general'

export interface MetricNotice {
    kind: 'notice'
    key: string
    title: string
    message: string
    /** Stands in the value's place for a metric that exists but cannot be computed here. */
    value?: string
    action?: { label: string; onClick: () => void; dataAttr: string }
}

export type MetricCardSpec = { kind: 'metric'; item: OverviewMetricCardItem } | MetricNotice

/** Percent change the way the cards want it: whole percent, and undefined when there is no
 * baseline to divide by. The backend sends a sentinel for that case, which the grid already hides. */
export function pctChange(value: number | undefined, previous: number | undefined): number | undefined {
    if (value === undefined || previous === undefined || previous === 0) {
        return undefined
    }
    return Math.round(((value - previous) / previous) * 100)
}

/** Picks named keys out of a WebOverviewQuery response, keeping the requested order. */
export function pickOverviewItems(results: WebOverviewItem[] | undefined, keys: string[]): MetricCardSpec[] {
    return keys.flatMap((key) => {
        const item = results?.find((result) => result.key === key)
        return item ? [{ kind: 'metric' as const, item: item as OverviewMetricCardItem }] : []
    })
}
