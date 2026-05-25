import type { TooltipContext } from 'lib/hog-charts'
import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import type { FunnelStepsBarSeriesMeta } from './funnelStepsBarTransforms'

interface FunnelStepsBarTooltipProps {
    context: TooltipContext<FunnelStepsBarSeriesMeta>
    steps: FunnelStepWithConversionMetrics[]
    breakdownFilter: BreakdownFilter | null | undefined
    groupTypeLabel: string
    showPersonsModal: boolean
}

export function FunnelStepsBarTooltip({
    context,
    steps,
    breakdownFilter,
    groupTypeLabel,
    showPersonsModal,
}: FunnelStepsBarTooltipProps): JSX.Element | null {
    const stepIndex = context.dataIndex
    const step = steps[stepIndex]
    const entry = context.seriesData[0]
    if (!step || !entry) {
        return null
    }

    const breakdownIndex = entry.series.meta?.breakdownIndex ?? 0
    const series = step.nested_breakdown?.[breakdownIndex] ?? step

    return (
        <FunnelTooltip
            embedded
            showPersonsModal={showPersonsModal}
            stepIndex={stepIndex}
            series={series}
            groupTypeLabel={groupTypeLabel}
            breakdownFilter={breakdownFilter}
        />
    )
}
