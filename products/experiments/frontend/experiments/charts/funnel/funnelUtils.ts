import { FunnelLayout } from 'lib/constants'
import { flattenedStepsByBreakdown, stepsWithConversionMetrics } from 'scenes/funnels/funnelUtils'

import {
    FlattenedFunnelStepByBreakdown,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
} from '~/types'

export interface FunnelDataProcessingOptions {
    stepReference?: FunnelStepReference
    disableBaseline?: boolean
    hiddenLegendBreakdowns?: string[]
}

export interface ProcessedFunnelData {
    steps: FunnelStepWithNestedBreakdown[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    flattenedBreakdowns: FlattenedFunnelStepByBreakdown[]
    hasFunnelResults: boolean
}

/**
 * Processes raw funnel step data into the format needed for visualization components.
 * This extracts the core data processing logic from funnelDataLogic.
 */
export function processFunnelData(
    steps: FunnelStepWithNestedBreakdown[],
    options: FunnelDataProcessingOptions = {}
): ProcessedFunnelData {
    const { stepReference = FunnelStepReference.total } = options

    // Sort steps by order (same as funnelDataLogic)
    const sortedSteps = steps.sort((a, b) => a.order - b.order)

    // Calculate conversion metrics
    const stepsWithMetrics = stepsWithConversionMetrics(sortedSteps, stepReference)

    // Flatten breakdowns for legend display (always use vertical layout)
    const flattenedBreakdowns = flattenedStepsByBreakdown(stepsWithMetrics, FunnelLayout.vertical, true)

    // Check if we have valid funnel results
    const hasFunnelResults = !!(sortedSteps && sortedSteps[0] && sortedSteps[0].count > -1)

    return {
        steps: sortedSteps,
        stepsWithConversionMetrics: stepsWithMetrics,
        flattenedBreakdowns,
        hasFunnelResults,
    }
}
