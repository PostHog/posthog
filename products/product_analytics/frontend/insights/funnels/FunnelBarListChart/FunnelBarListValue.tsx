import { percentage } from 'lib/utils/numbers'

import { type Noun } from '~/models/groupsModel'
import { type FunnelStepWithConversionMetrics } from '~/types'

import { periodTotals } from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { funnelConversionRate } from '../shared/funnelBarHorizontalShared'
import { FunnelBarListCount } from './FunnelBarListCount'
import { type FunnelBarListDetail } from './useFunnelBarListDetail'

export interface FunnelBarListValueProps {
    step: FunnelStepWithConversionMetrics
    firstStep: FunnelStepWithConversionMetrics
    period?: 'current' | 'previous'
    aggregationTargetLabel: Noun
    detail: FunnelBarListDetail
}

export function FunnelBarListValue({
    step,
    firstStep,
    period,
    aggregationTargetLabel,
    detail,
}: FunnelBarListValueProps): JSX.Element {
    const count = period ? periodTotals(step)[period] : step.count
    // Compare bars are scaled to the larger period, so show this period's own conversion.
    const rate = period
        ? funnelConversionRate(count, periodTotals(firstStep)[period])
        : step.conversionRates.fromBasisStep
    return (
        <span className="text-secondary" translate="no">
            <span className="font-semibold text-primary">{percentage(rate, 1)}</span>
            <FunnelBarListCount
                count={count}
                aggregationTargetLabel={aggregationTargetLabel}
                verb="converted"
                detail={detail}
            />
        </span>
    )
}
