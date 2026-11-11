import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { type Noun } from '~/models/groupsModel'
import { type FunnelStepWithConversionMetrics } from '~/types'

import { periodTotals } from '../FunnelBarHorizontalChart/funnelBarHorizontalTransforms'
import { funnelConversionRate } from '../shared/funnelBarHorizontalShared'

export interface FunnelBarListValueProps {
    step: FunnelStepWithConversionMetrics
    firstStep: FunnelStepWithConversionMetrics
    period?: 'current' | 'previous'
    aggregationTargetLabel: Noun
}

export function FunnelBarListValue({
    step,
    firstStep,
    period,
    aggregationTargetLabel,
}: FunnelBarListValueProps): JSX.Element {
    const count = period ? periodTotals(step)[period] : step.count
    // Compare bars are scaled to the larger period, so show this period's own conversion.
    const rate = period
        ? funnelConversionRate(count, periodTotals(firstStep)[period])
        : step.conversionRates.fromBasisStep
    return (
        <span className="text-secondary" translate="no">
            <span className="font-semibold text-primary">{percentage(rate, 1)}</span>
            <span className="@max-xl:hidden">{` (${humanFriendlyNumber(count)} ${pluralize(count, aggregationTargetLabel.singular, aggregationTargetLabel.plural, false)})`}</span>
            <span className="@max-sm:hidden"> converted</span>
        </span>
    )
}
