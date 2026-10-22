import { IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { type Noun } from '~/models/groupsModel'
import { type FunnelStepWithConversionMetrics } from '~/types'

export interface FunnelBarListDropOffProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    period?: 'current' | 'previous'
    aggregationTargetLabel: Noun
}

export function FunnelBarListDropOff({
    step,
    stepIndex,
    period,
    aggregationTargetLabel,
}: FunnelBarListDropOffProps): JSX.Element | null {
    if (stepIndex === 0 || period) {
        return null
    }
    return (
        <span className="flex items-center gap-0.5 text-sm leading-4 text-secondary @max-sm:hidden">
            <IconTrendingFlatDown className="text-danger" />
            <span>
                {percentage(1 - step.conversionRates.fromPrevious, 1)}
                <span className="@max-xl:hidden">{` (${humanFriendlyNumber(step.droppedOffFromPrevious)} ${pluralize(step.droppedOffFromPrevious, aggregationTargetLabel.singular, aggregationTargetLabel.plural, false)})`}</span>
                {' dropped off'}
            </span>
        </span>
    )
}
