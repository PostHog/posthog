import { formatMetricValue } from '@/model/adapters/metric'
import type { MetricFormat } from '@/model/types'

/** "Last 14 days · 2 filters". The filter part is left out when there are none. */
export function metricSourceLabel(windowLabel: string, filterCount: number): string {
    if (filterCount <= 0) {
        return windowLabel
    }
    return `${windowLabel} · ${filterCount} ${filterCount === 1 ? 'filter' : 'filters'}`
}

export function valueFormatter(format: MetricFormat): (value: number) => string {
    return (value) => formatMetricValue(value, format.valueFormat, format.unit)
}
