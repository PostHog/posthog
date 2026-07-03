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
    /** Compare mode: the period a segment belongs to. Set on the breakdown + compare aggregate
     *  drop-off band — its `breakdownIndex` is null (it spans every value of the period), so this
     *  is what lets a click scope the persons modal to the right period. */
    compareLabel?: 'current' | 'previous'
}

/** Series for one step's single-band bar. Each series' `data` has exactly one value. */
export interface FunnelBarHorizontalStepData {
    /** Band label — a single per-chart slot, so just the step index as a string. */
    label: string
    series: Series<FunnelBarHorizontalSegmentMeta>[]
}

/** Trailing grey band that fills the bar up to 100% so every step reads against the same axis.
 *  `breakdownIndex` tags the filler with its period/variant in compare mode so a drop-off click
 *  resolves the right series; it stays null for the single-bar and breakdown paths. */
export function buildFunnelBarHorizontalFiller(
    segments: Series<FunnelBarHorizontalSegmentMeta>[],
    color: string,
    breakdownIndex: number | null = null
): Series<FunnelBarHorizontalSegmentMeta> {
    const covered = segments.reduce((sum, s) => sum + (s.data[0] ?? 0), 0)
    return {
        key: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
        label: 'Drop-off',
        data: [Math.max(0, RATE_TO_PERCENT - covered)],
        color,
        visibility: { tooltip: false },
        meta: { isDropOff: true, breakdownIndex },
    }
}

/** Compare-mode drop-off band: fills from the converted segments up to a period's own entry level
 *  (its first-step share of the shared baseline) rather than to 100%. The space above the entry level
 *  is the volume gap — this period simply had fewer entrants — and is left as blank axis whitespace,
 *  visually distinct from drop-off and non-interactive: `trackData` declares the entry level as the
 *  bar's interactive ceiling, so the chart suppresses hover, tooltip, pointer cursor, and click in
 *  the gap. The leader period's entry level is 100, so it fills the track exactly like the
 *  non-compare filler. */
export function buildFunnelBarHorizontalDropOff(
    segments: Series<FunnelBarHorizontalSegmentMeta>[],
    entryLevelPercent: number,
    color: string,
    breakdownIndex: number | null = null,
    compareLabel?: 'current' | 'previous'
): Series<FunnelBarHorizontalSegmentMeta> {
    const covered = segments.reduce((sum, s) => sum + (s.data[0] ?? 0), 0)
    return {
        key: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
        label: 'Drop-off',
        data: [Math.max(0, entryLevelPercent - covered)],
        color,
        visibility: { tooltip: false },
        meta: { isDropOff: true, breakdownIndex, compareLabel },
        trackData: [entryLevelPercent],
    }
}

/** Everything the MCP funnel view needs to render one step — all conversion math precomputed so the
 *  view stays presentational. */
export interface FunnelBarRow {
    stepIndex: number
    name: string
    count: number
    /** Conversion relative to the first step (0..1) — drives bar length and the per-step label. */
    fractionOfBasis: number
    /** Conversion relative to the previous step (0..1); 0 for the first step (not displayed). */
    fromPrevious: number
    stepData: FunnelBarHorizontalStepData
}

export interface FunnelBarsModel {
    rows: FunnelBarRow[]
    overall: { rate: number; firstCount: number; lastCount: number }
}

/** Precomputes the per-step conversion rows + overall conversion for the (non-breakdown) MCP funnel,
 *  so the visualizer is pure rendering and the rate/divide-by-zero math is unit-tested here. */
export function buildFunnelBars(
    steps: { name: string; count: number }[],
    opts: { color: string; fillerColor: string }
): FunnelBarsModel {
    const firstCount = steps[0]?.count ?? 0
    const lastCount = steps[steps.length - 1]?.count ?? 0
    const rows = steps.map((step, stepIndex) => {
        const fractionOfBasis = funnelConversionRate(step.count, firstCount)
        return {
            stepIndex,
            name: step.name,
            count: step.count,
            fractionOfBasis,
            fromPrevious: funnelConversionRate(step.count, steps[stepIndex - 1]?.count ?? 0),
            stepData: buildFunnelConversionStep({
                stepIndex,
                label: step.name,
                fractionOfBasis,
                color: opts.color,
                fillerColor: opts.fillerColor,
            }),
        }
    })
    return { rows, overall: { rate: funnelConversionRate(lastCount, firstCount), firstCount, lastCount } }
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
