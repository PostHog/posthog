import type { BarChartConfig, ChartMargins, Series, TooltipConfig } from '@posthog/quill-charts'

import { funnelConversionRate, RATE_TO_PERCENT } from './funnelBarHorizontalShared'

// Dependency-neutral primitives for the vertical (grouped) funnel bars, shared by the web container
// (FunnelStepsBarChart) and the MCP UI app. Like funnelBarHorizontalShared.ts, this is free of `~/`,
// `lib/`, and `scenes/` imports so it compiles in the MCP Vite bundle, which only resolves `products/*`
// and `@posthog/*`.

export const FUNNEL_STEPS_BAR_SERIES_KEY = 'funnel-steps-bar-series'

/** Inner gap between bars as a fraction of the band slot. Exported because the web container also
 *  needs it for its per-step legend width math. */
export const FUNNEL_STEPS_BAND_PADDING = 0.1

export interface FunnelStepsBarConfigOptions {
    /** Hide x-axis category labels — the web container renders its own StepLegend row instead. */
    hideXAxis?: boolean
    /** Truncate long category (step-name) labels to this px width; omit to render untruncated. */
    maxCategoryLabelWidth?: number
    /** Tooltip anchor. The web container pins to `top`; the compact MCP app tracks the `cursor`. */
    tooltipPlacement?: TooltipConfig['placement']
    margins?: Partial<ChartMargins>
    animateHover?: boolean
}

/** Grouped vertical bars with a hatched track behind each (the "share of a whole" funnel look) and a
 *  percent value axis. Shared by the web FunnelStepsBarChart and the MCP funnel app so the bar styling
 *  and axis stay identical; per-surface differences (axis labels, tooltip anchor, margins) are options. */
export function buildFunnelStepsBarConfig(options: FunnelStepsBarConfigOptions = {}): BarChartConfig {
    return {
        barLayout: 'grouped',
        showGrid: true,
        animateHover: options.animateHover,
        hideXAxis: options.hideXAxis,
        maxCategoryLabelWidth: options.maxCategoryLabelWidth,
        margins: options.margins,
        yTickFormatter: (value) => `${Math.round(value)}%`,
        tooltip: { placement: options.tooltipPlacement ?? 'top' },
        bars: {
            cornerRadius: 10,
            track: true,
            shadow: { color: 'rgba(0,0,0,0.15)', blur: 6, offsetY: -2 },
            bandPadding: FUNNEL_STEPS_BAND_PADDING,
        },
    }
}

/** Per-step conversion data, indexed to match the chart's `dataIndex` so a tooltip can look it up. */
export interface FunnelStepsBarRow {
    stepIndex: number
    name: string
    count: number
    /** Conversion relative to the first step (0..1). */
    fractionOfBasis: number
    /** Conversion relative to the previous step (0..1); 0 for the first step. */
    fromPrevious: number
}

/** A grouped-bar series already resolved to per-step conversion percentages. Each surface produces these
 *  its own way — the MCP app from raw counts, the web container from per-breakdown conversion rates — and
 *  hands them to `buildFunnelStepsBars`, which owns the shared band labels, rows, and overall stats. */
export interface FunnelStepsBarVariant<TMeta = unknown> {
    key: string
    label: string
    color?: string
    meta?: TMeta
    /** `data[stepIndex]` is the conversion from the first step, as a percent (0–100). The `track: true`
     *  bar config draws the drop-off remainder up to 100%. */
    data: number[]
    /** Compare only: per-step track ceiling (percent) — caps the drop-off track at this period's entry
     *  level so the volume gap above it is left blank. Omit for the default full-height track. */
    trackData?: number[]
}

export interface FunnelStepsBarsModel<TMeta = unknown> {
    /** One grouped series per variant (a single series without a breakdown). */
    series: Series<TMeta>[]
    /** X-axis band labels — 1-based step indices as strings. Always unique, so steps that share an event
     *  name (e.g. two `$pageview` steps) don't collapse onto one band slot; surfaces map the index back to
     *  the step name for display (web's StepLegend row, the MCP app's `xTickFormatter`). */
    labels: string[]
    rows: FunnelStepsBarRow[]
    overall: { rate: number; firstCount: number; lastCount: number }
}

/** Assembles the grouped vertical-bar model shared by the web FunnelStepsBarChart and the MCP funnel app.
 *  Callers resolve their own per-variant series (single for MCP, one-per-breakdown for web); this owns the
 *  pieces that must stay identical across surfaces: the index-keyed band labels, the per-step conversion
 *  rows, and the overall first→last rate. */
export function buildFunnelStepsBars<TMeta = unknown>(
    steps: { name: string; count: number }[],
    variants: FunnelStepsBarVariant<TMeta>[]
): FunnelStepsBarsModel<TMeta> {
    const firstCount = steps[0]?.count ?? 0
    const lastCount = steps[steps.length - 1]?.count ?? 0
    const rows: FunnelStepsBarRow[] = steps.map((step, stepIndex) => ({
        stepIndex,
        name: step.name,
        count: step.count,
        fractionOfBasis: funnelConversionRate(step.count, firstCount),
        fromPrevious: funnelConversionRate(step.count, steps[stepIndex - 1]?.count ?? 0),
    }))
    const series: Series<TMeta>[] = variants.map((variant) => ({
        key: variant.key,
        label: variant.label,
        data: variant.data,
        color: variant.color,
        meta: variant.meta,
        trackData: variant.trackData,
    }))
    return {
        series,
        labels: steps.map((_, stepIndex) => `${stepIndex + 1}`),
        rows,
        overall: { rate: funnelConversionRate(lastCount, firstCount), firstCount, lastCount },
    }
}

/** Convenience for the single-series (non-breakdown) funnel — the MCP app and the web no-breakdown path.
 *  Derives the lone "conversion from the first step" series from raw counts, then defers to
 *  `buildFunnelStepsBars` for the shared labels, rows, and overall stats. */
export function buildSingleSeriesFunnelStepsBars(
    steps: { name: string; count: number }[],
    opts: { color: string }
): FunnelStepsBarsModel {
    const firstCount = steps[0]?.count ?? 0
    const data = steps.map((step) => funnelConversionRate(step.count, firstCount) * RATE_TO_PERCENT)
    return buildFunnelStepsBars(steps, [
        { key: FUNNEL_STEPS_BAR_SERIES_KEY, label: 'Conversion', color: opts.color, data },
    ])
}
