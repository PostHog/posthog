import { useValues } from 'kea'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { insightLogic } from 'scenes/insights/insightLogic'

import { funnelDataLogic } from '../funnelDataLogic'
import { FunnelStepPathLinks } from './FunnelStepPathLinks'

type FunnelStepMoreProps = {
    stepIndex: number
    className?: string
}

export function FunnelStepMore({ stepIndex, className }: FunnelStepMoreProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (querySource?.aggregation_group_type_index != null) {
        return null
    }

    return (
        <More
            className={className}
            placement="bottom-start"
            noPadding
            overlay={<FunnelStepPathLinks stepIndex={stepIndex} />}
        />
    )
}
