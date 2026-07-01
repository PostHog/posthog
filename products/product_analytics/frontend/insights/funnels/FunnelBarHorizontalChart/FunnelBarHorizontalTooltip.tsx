import { useValues } from 'kea'

import type { TooltipContext } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import { funnelComparePeriodDateRange, getFunnelAggregateConversionRate } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepTooltip } from '../shared/FunnelStepTooltip'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]

    const entry = context.seriesData[0]
    if (!entry) {
        return null
    }

    const breakdownIndex = entry.series.meta?.breakdownIndex
    const series =
        breakdownIndex != null && step.nested_breakdown?.[breakdownIndex] ? step.nested_breakdown[breakdownIndex] : step
    const aggregateConversionRate = getFunnelAggregateConversionRate(series, step)
    const comparePeriodDateRange = series.compare_label
        ? funnelComparePeriodDateRange(series.compare_label, resolvedDateRange, compareTo)
        : null

    // Horizontal bar chart: cursor right of the bar's end pixel is in the track (drop-off) region.
    const isDropOffHover =
        stepIndex > 0 && context.hoverPosition != null && entry.yPixel != null && context.hoverPosition.x > entry.yPixel

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
        <FunnelTooltip {...sharedProps} />
    )
}
