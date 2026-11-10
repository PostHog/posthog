import { useNow } from '@/lib/useNow'
import type { MetricView } from '@/model/types'

import { useMetricAggregate } from './hooks'
import { type MetricValueState, metricValueState } from './metricValue'

/** The value to show for a metric: live when the query answers, else the saved snapshot. */
export function useMetricValue(metric: MetricView): MetricValueState {
    const aggregate = useMetricAggregate(metric.data)
    const now = useNow()
    return metricValueState(aggregate, metric, now)
}
