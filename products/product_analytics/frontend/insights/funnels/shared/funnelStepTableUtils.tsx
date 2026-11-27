import { FlattenedFunnelStepByBreakdown, FunnelStepWithConversionMetrics } from '~/types'

export function getSignificanceFromBreakdownStep(
    breakdown: FlattenedFunnelStepByBreakdown,
    stepOrder: number
): FunnelStepWithConversionMetrics['significant'] {
    return breakdown.steps?.[stepOrder]?.significant
}
