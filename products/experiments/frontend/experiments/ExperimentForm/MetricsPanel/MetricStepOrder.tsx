import { match } from 'ts-pattern'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { StepOrderValue } from '~/types'

/**
 * Only for funnel metrics
 */
export type MetricStepOrderProps = {
    metric: ExperimentMetric
}

export const MetricStepOrder = ({ metric }: MetricStepOrderProps): JSX.Element | null => {
    if (!isExperimentFunnelMetric(metric)) {
        return null
    }

    const orderLabel = match(metric.funnel_order_type)
        .with(StepOrderValue.ORDERED, () => 'Sequential')
        .with(StepOrderValue.UNORDERED, () => 'Any order')
        .otherwise(() => 'Sequential')

    return (
        <div className="text-xs">
            <span className="text-muted">Step order:</span> <span className="font-semibold">{orderLabel}</span>
        </div>
    )
}
