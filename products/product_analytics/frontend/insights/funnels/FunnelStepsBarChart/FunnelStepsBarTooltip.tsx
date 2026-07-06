import { useValues } from 'kea'

import type { TooltipContext } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import { funnelComparePeriodDateRange, getFunnelAggregateConversionRate } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepTooltip } from '../shared/FunnelStepTooltip'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]

    const stepIndex = context.dataIndex
    const step = steps[stepIndex]
    const entry = context.seriesData[0]
    if (!step || !entry) {
        return null
    }

    const breakdownIndex = entry.series.meta?.breakdownIndex ?? 0
    const series = step.nested_breakdown?.[breakdownIndex] ?? step
    const aggregateConversionRate = getFunnelAggregateConversionRate(series, step)
    const comparePeriodDateRange = series.compare_label
        ? funnelComparePeriodDateRange(series.compare_label, resolvedDateRange, compareTo)
        : null

    // Vertical bar chart: cursor above the bar's top pixel is in the track (drop-off) region.
    const isDropOffHover =
        stepIndex > 0 && context.hoverPosition != null && entry.yPixel != null && context.hoverPosition.y < entry.yPixel

    const sharedProps = {
        showPersonsModal,
        stepIndex,
        series,
        groupTypeLabel,
        breakdownFilter,
        aggregateConversionRate,
        comparePeriodDateRange,
    }

    return quillTooltipEnabled ? (
        <FunnelStepTooltip {...sharedProps} isDropOffHover={isDropOffHover} color={entry.color} />
    ) : (
        <FunnelTooltip {...sharedProps} isDropOffHover={isDropOffHover} />
    )
}
