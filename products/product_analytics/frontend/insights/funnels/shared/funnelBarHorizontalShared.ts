import type { Series } from '@posthog/quill-charts'

// Dependency-neutral primitives for the horizontal funnel bars, shared by the web container
// (funnelBarHorizontalTransforms.ts) and the MCP UI app. Deliberately free of `~/`, `lib/`, and
// `scenes/` imports so they compile in the MCP Vite bundle, which only resolves `products/*` and
// `@posthog/*`.

export const FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX = 'funnel-bar-horizontal-segment-'
export const FUNNEL_BAR_HORIZONTAL_FILLER_KEY = 'funnel-bar-horizontal-filler'

/** Every step's bar is its own single-band chart, so they only line up if they share this
 *  value domain (passed to BarChart as `bars.valueDomain`). Segment data are basis-step
 *  percentages, so the axis is `0–100`. */
export const FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN: [number, number] = [0, 100]

export const RATE_TO_PERCENT = 100

/** Conversion of a step's count against a basis count, as a 0..1 rate. A zero or absent basis
 *  yields 0 (rather than dividing by zero) so the bar collapses instead of rendering NaN. */
export function funnelConversionRate(count: number, basisCount: number): number {
    return basisCount > 0 ? count / basisCount : 0
}

export interface FunnelBarHorizontalSegmentMeta {
    isDropOff: boolean
    breakdownIndex: number | null
}

/** Series for one step's single-band bar. Each series' `data` has exactly one value. */
export interface FunnelBarHorizontalStepData {
    /** Band label — a single per-chart slot, so just the step index as a string. */
    label: string
    series: Series<FunnelBarHorizontalSegmentMeta>[]
}

/** Trailing grey band that fills the bar up to 100% so every step reads against the same axis. */
export function buildFunnelBarHorizontalFiller(
    segments: Series<FunnelBarHorizontalSegmentMeta>[],
    color: string
): Series<FunnelBarHorizontalSegmentMeta> {
    const covered = segments.reduce((sum, s) => sum + (s.data[0] ?? 0), 0)
    return {
        key: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
        label: 'Drop-off',
        data: [Math.max(0, RATE_TO_PERCENT - covered)],
        color,
        visibility: { tooltip: false },
        meta: { isDropOff: true, breakdownIndex: null },
    }
}

/** Build a single-segment step bar (no breakdown) plus its drop-off filler. `fractionOfBasis` is a
 *  0..1 conversion rate relative to the basis step. Shared by the web single-segment path and the
 *  simpler MCP funnel, which has no breakdown variants. */
export function buildFunnelConversionStep(opts: {
    stepIndex: number
    label: string
    fractionOfBasis: number
    color: string
    fillerColor: string
}): FunnelBarHorizontalStepData {
    const segment: Series<FunnelBarHorizontalSegmentMeta> = {
        key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
        label: opts.label,
        data: [opts.fractionOfBasis * RATE_TO_PERCENT],
        color: opts.color,
        meta: { isDropOff: false, breakdownIndex: null },
    }
    return {
        label: String(opts.stepIndex),
        series: [segment, buildFunnelBarHorizontalFiller([segment], opts.fillerColor)],
    }
}
