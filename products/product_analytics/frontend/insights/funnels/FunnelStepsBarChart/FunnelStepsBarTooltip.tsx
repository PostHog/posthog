import type { TooltipContext } from '@posthog/quill-charts'

import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import { funnelComparePeriodDateRange, hasBreakdown } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import type { FunnelStepsBarSeriesMeta } from './funnelStepsBarTransforms'

interface FunnelStepsBarTooltipProps {
    context: TooltipContext<FunnelStepsBarSeriesMeta>
    steps: FunnelStepWithConversionMetrics[]
    breakdownFilter: BreakdownFilter | null | undefined
    groupTypeLabel: string
    showPersonsModal: boolean
    resolvedDateRange?: Parameters<typeof funnelComparePeriodDateRange>[1]
    compareTo?: Parameters<typeof funnelComparePeriodDateRange>[2]
}

export function FunnelStepsBarTooltip({
    context,
    steps,
    breakdownFilter,
    groupTypeLabel,
    showPersonsModal,
    resolvedDateRange,
    compareTo,
}: FunnelStepsBarTooltipProps): JSX.Element | null {
    const stepIndex = context.dataIndex
    const step = steps[stepIndex]
    const entry = context.seriesData[0]
    if (!step || !entry) {
        return null
    }

    const breakdownIndex = entry.series.meta?.breakdownIndex ?? 0
    const series = step.nested_breakdown?.[breakdownIndex] ?? step
    // Only surface the aggregate for genuine breakdowns (not compare-only, not breakdown+compare).
    const aggregateConversionRate =
        series !== step && hasBreakdown(series.breakdown_value) && !series.compare_label
            ? step.conversionRates.total
            : null

    return (
        <FunnelTooltip
            showPersonsModal={showPersonsModal}
            stepIndex={stepIndex}
            series={series}
            groupTypeLabel={groupTypeLabel}
            breakdownFilter={breakdownFilter}
            aggregateConversionRate={aggregateConversionRate}
            comparePeriodDateRange={
                series.compare_label
                    ? funnelComparePeriodDateRange(series.compare_label, resolvedDateRange, compareTo)
                    : null
            }
        />
    )
}
