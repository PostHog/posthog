import { useValues } from 'kea'

import type { TooltipContext } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelTooltip } from 'scenes/funnels/FunnelTooltip'
import { funnelComparePeriodDateRange, getFunnelAggregateConversionRate } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepTooltip } from '../shared/FunnelStepTooltip'
import { type FunnelBarHorizontalSegmentMeta, resolveFunnelBarHorizontalHover } from './funnelBarHorizontalTransforms'

interface FunnelBarHorizontalTooltipProps {
    context: TooltipContext<FunnelBarHorizontalSegmentMeta>
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    /** First funnel step — basis for a compare stack drop-off's period-aggregate from-start rate. */
    firstStep: FunnelStepWithConversionMetrics
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
    firstStep,
    breakdownFilter,
    groupTypeLabel,
    showPersonsModal,
    resolvedDateRange,
    compareTo,
}: FunnelBarHorizontalTooltipProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]

    const target = resolveFunnelBarHorizontalHover(context, step, stepIndex, firstStep)
    if (!target) {
        return null
    }

    const { series, isDropOffHover, color } = target
    const aggregateConversionRate = getFunnelAggregateConversionRate(series, step)
    const comparePeriodDateRange = series.compare_label
        ? funnelComparePeriodDateRange(series.compare_label, resolvedDateRange, compareTo)
        : null

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
        <FunnelStepTooltip {...sharedProps} isDropOffHover={isDropOffHover} color={color} />
    ) : (
        <FunnelTooltip {...sharedProps} isDropOffHover={isDropOffHover} />
    )
}
