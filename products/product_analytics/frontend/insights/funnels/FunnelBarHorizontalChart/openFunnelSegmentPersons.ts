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

export function openFunnelSegmentPersons(
    step: FunnelStepWithConversionMetrics,
    meta: FunnelBarHorizontalSegmentMeta,
    isComparedFunnel: boolean,
    { openPersonsModalForStep, openPersonsModalForSeries }: FunnelPersonsModalActions
): void {
    // Breakdown + compare: the drop-off spans every breakdown value, so open the period's whole-step drop-off.
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
    // Compare: open the period's series here, before the generic drop-off branch opens the whole step.
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
