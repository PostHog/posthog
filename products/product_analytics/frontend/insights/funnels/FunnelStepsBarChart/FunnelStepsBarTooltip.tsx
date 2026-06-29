import type { TooltipContext } from '@posthog/quill-charts'

import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import {
    funnelComparePeriodDateRange,
    getFunnelAggregateConversionRate,
    hasBreakdown,
} from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import { FUNNEL_NOT_PRESENT_TOOLTIP } from '../shared/funnelBarHorizontalShared'
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
    const aggregateConversionRate = getFunnelAggregateConversionRate(series, step)

    // This period had fewer entrants than the other when its step-0 sits below the shared baseline —
    // the headroom above its capped track is the volume gap, so flag it as "not present", not
    // drop-off. Pure compare only — in breakdown × compare the headroom isn't a period gap.
    const isShorterComparePeriod =
        series.compare_label != null &&
        !hasBreakdown(series.breakdown_value) &&
        (steps[0]?.nested_breakdown?.[breakdownIndex]?.conversionRates.fromBasisStep ?? 1) < 1

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
            footerNote={isShorterComparePeriod ? FUNNEL_NOT_PRESENT_TOOLTIP : null}
        />
    )
}
