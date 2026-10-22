import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { type FunnelStepWithConversionMetrics } from '~/types'

import { periodTotals } from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { funnelConversionRate } from '../shared/funnelBarHorizontalShared'

export interface FunnelBarListValueProps {
    step: FunnelStepWithConversionMetrics
    firstStep: FunnelStepWithConversionMetrics
    period?: 'current' | 'previous'
}

export function FunnelBarListValue({ step, firstStep, period }: FunnelBarListValueProps): JSX.Element {
    const count = period ? periodTotals(step)[period] : step.count
    // Compare bars are scaled to the larger period, so show this period's own conversion.
    const rate = period
        ? funnelConversionRate(count, periodTotals(firstStep)[period])
        : step.conversionRates.fromBasisStep
    return (
        <>
            {percentage(rate, 1)}
            <span className="@max-md:hidden"> · {humanFriendlyNumber(count)}</span>
        </>
    )
}
