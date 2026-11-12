import { IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils/numbers'

import { type Noun } from '~/models/groupsModel'
import { type FunnelStepWithConversionMetrics } from '~/types'

import { FunnelBarListCount } from './FunnelBarListCount'
import { type FunnelBarListDetail } from './useFunnelBarListDetail'

export interface FunnelBarListDropOffProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    period?: 'current' | 'previous'
    aggregationTargetLabel: Noun
    detail: FunnelBarListDetail
}

export function FunnelBarListDropOff({
    step,
    stepIndex,
    period,
    aggregationTargetLabel,
    detail,
}: FunnelBarListDropOffProps): JSX.Element | null {
    if (stepIndex === 0 || period) {
        return null
    }
    return (
        <span className="flex items-center gap-0.5 text-xs text-secondary">
            <IconTrendingFlatDown className="text-danger" />
            <span>
                <span>{percentage(1 - step.conversionRates.fromPrevious, 1)}</span>
                <FunnelBarListCount
                    count={step.droppedOffFromPrevious}
                    aggregationTargetLabel={aggregationTargetLabel}
                    verb="dropped off"
                    detail={detail}
                />
            </span>
        </span>
    )
}
