import type { TooltipContext } from '@posthog/quill-charts'

import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import { funnelComparePeriodDateRange } from 'scenes/funnels/funnelUtils'

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
    resolvedDateRange?: Parameters<typeof funnelComparePeriodDateRange>[1]
    compareTo?: Parameters<typeof funnelComparePeriodDateRange>[2]
}

export function FunnelBarHorizontalTooltip({
    context,
    step,
    stepIndex,
    breakdownFilter,
    groupTypeLabel,
    showPersonsModal,
    resolvedDateRange,
    compareTo,
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
            comparePeriodDateRange={
                series.compare_label
                    ? funnelComparePeriodDateRange(series.compare_label, resolvedDateRange, compareTo)
                    : null
            }
        />
    )
}
