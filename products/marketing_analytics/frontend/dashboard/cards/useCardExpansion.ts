import { useActions, useValues } from 'kea'

import { metricChartSpec } from '../charts/metricChartSpec'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import type { MetricCardSpec } from './metricCardSpec'

export function useCardExpansion(): (spec: MetricCardSpec) => MetricCardSpec {
    const { expandedMetric, selectedConversionGoal } = useValues(marketingDashboardLogic)
    const { toggleExpandedMetric } = useActions(marketingDashboardLogic)

    return (spec: MetricCardSpec): MetricCardSpec => {
        if (spec.kind !== 'metric') {
            return spec
        }
        const key = spec.item.key
        if (!metricChartSpec(key, selectedConversionGoal)) {
            return spec
        }
        return {
            ...spec,
            item: {
                ...spec.item,
                onClick: () => toggleExpandedMetric(key),
                selected: expandedMetric === key,
            },
        }
    }
}
