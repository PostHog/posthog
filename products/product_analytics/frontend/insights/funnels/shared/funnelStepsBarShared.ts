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

export interface FunnelStepsBarsModel {
    /** Single grouped series whose `data[stepIndex]` is the step's conversion from the first step, as
     *  a percent (0–100). The `track: true` bar config draws the drop-off remainder up to 100%. */
    series: Series[]
    /** X-axis category labels — the step names. */
    labels: string[]
    rows: FunnelStepsBarRow[]
    overall: { rate: number; firstCount: number; lastCount: number }
}

/** Builds the grouped vertical-bar data for the simple (non-breakdown) MCP funnel. Mirrors the web
 *  FunnelStepsBarChart's single-variant path: one series valued by conversion rate from the basis step. */
export function buildFunnelStepsBars(
    steps: { name: string; count: number }[],
    opts: { color: string }
): FunnelStepsBarsModel {
    const firstCount = steps[0]?.count ?? 0
    const lastCount = steps[steps.length - 1]?.count ?? 0
    const rows: FunnelStepsBarRow[] = steps.map((step, stepIndex) => ({
        stepIndex,
        name: step.name,
        count: step.count,
        fractionOfBasis: funnelConversionRate(step.count, firstCount),
        fromPrevious: funnelConversionRate(step.count, steps[stepIndex - 1]?.count ?? 0),
    }))
    const series: Series[] = [
        {
            key: FUNNEL_STEPS_BAR_SERIES_KEY,
            label: 'Conversion',
            data: rows.map((row) => row.fractionOfBasis * RATE_TO_PERCENT),
            color: opts.color,
        },
    ]
    return {
        series,
        labels: steps.map((step) => step.name),
        rows,
        overall: { rate: funnelConversionRate(lastCount, firstCount), firstCount, lastCount },
    }
}
