import { type FunnelStep, type FunnelStepWithConversionMetrics } from '~/types'

import { type FunnelBarHorizontalSegmentMeta } from './funnelBarHorizontalTransforms'

interface FunnelPersonsModalActions {
    openPersonsModalForStep: (payload: { step: FunnelStep; converted: boolean }) => void
    openPersonsModalForSeries: (payload: {
        step: FunnelStep
        series: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>
        converted: boolean
    }) => void
}

/** Opens the persons modal for a clicked horizontal funnel segment: a breakdown value, a compare
 *  period, or the drop-off band. */
export function openFunnelSegmentPersons(
    step: FunnelStepWithConversionMetrics,
    meta: FunnelBarHorizontalSegmentMeta,
    isComparedFunnel: boolean,
    { openPersonsModalForStep, openPersonsModalForSeries }: FunnelPersonsModalActions
): void {
    // Stacked breakdown + compare: the drop-off band aggregates every value for the
    // period, so open the period's whole-step drop-off — compare-scoped, but with no
    // breakdown filter. Pure compare tags each drop-off with its period's
    // breakdownIndex instead, so it routes through the series branch below.
    if (isComparedFunnel && meta.isDropOff && meta.breakdownIndex == null) {
        if (meta.compareLabel) {
            openPersonsModalForSeries({
                step,
                series: {
                    ...step,
                    breakdown: undefined,
                    breakdown_value: undefined,
                    compare_label: meta.compareLabel,
                },
                converted: false,
            })
        }
        return
    }
    // Compare: both the bar and its drop-off filler carry a period breakdownIndex, so
    // route the matching period series (converted vs. dropped-off) — handled before the
    // generic drop-off branch, which would otherwise open the aggregate step.
    if (isComparedFunnel && meta.breakdownIndex != null && step.nested_breakdown?.[meta.breakdownIndex]) {
        openPersonsModalForSeries({
            step,
            series: step.nested_breakdown[meta.breakdownIndex],
            converted: !meta.isDropOff,
        })
        return
    }
    if (meta.isDropOff) {
        openPersonsModalForStep({ step, converted: false })
        return
    }
    if (meta.breakdownIndex != null && step.nested_breakdown?.[meta.breakdownIndex]) {
        openPersonsModalForSeries({
            step,
            series: step.nested_breakdown[meta.breakdownIndex],
            converted: true,
        })
        return
    }
    openPersonsModalForStep({ step, converted: true })
}
