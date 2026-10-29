import { CHART_DEFAULT_HEIGHT } from './chartMath'
import type { ChartVariant } from './types'

/** The Chart pin's plot height. The pin row around it is 176pt. */
export const COMPACT_CHART_HEIGHT = 96

export function chartHeight(variant: ChartVariant, height: number | undefined): number {
    return height ?? (variant === 'compact' ? COMPACT_CHART_HEIGHT : CHART_DEFAULT_HEIGHT)
}
