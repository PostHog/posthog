import type { TooltipContext } from '@posthog/quill-charts'

import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import type { FunnelBarHorizontalSegmentMeta } from './funnelBarHorizontalTransforms'

interface FunnelBarHorizontalTooltipProps {
    context: TooltipContext<FunnelBarHorizontalSegmentMeta>
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    breakdownFilter: BreakdownFilter | null | undefined
    groupTypeLabel: string
    showPersonsModal: boolean
}

export function FunnelBarHorizontalTooltip({
    context,
    step,
    stepIndex,
    breakdownFilter,
    groupTypeLabel,
    showPersonsModal,
}: FunnelBarHorizontalTooltipProps): JSX.Element | null {
    const entry = context.seriesData[0]
    if (!entry) {
        return null
    }

    const breakdownIndex = entry.series.meta?.breakdownIndex
    const series =
        breakdownIndex != null && step.nested_breakdown?.[breakdownIndex] ? step.nested_breakdown[breakdownIndex] : step

    return (
        <FunnelTooltip
            showPersonsModal={showPersonsModal}
            stepIndex={stepIndex}
            series={series}
            groupTypeLabel={groupTypeLabel}
            breakdownFilter={breakdownFilter}
        />
    )
}
