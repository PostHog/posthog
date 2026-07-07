import type { ChartStyle } from '~/queries/schema/schema-general'

/** Canvas dash patterns for the persisted line styles (px drawn / px gap). */
export const LINE_STYLE_DASH_PATTERNS: Record<'dashed' | 'dotted', number[]> = {
    dashed: [8, 4],
    dotted: [2, 3],
}

/** Radius used for data-point markers when `chartStyle.showPoints` is on. */
export const CHART_STYLE_POINT_RADIUS = 3

export function chartStyleCurve(chartStyle: ChartStyle | null | undefined): 'linear' | 'monotone' | undefined {
    if (!chartStyle?.curve) {
        return undefined
    }
    return chartStyle.curve === 'smooth' ? 'monotone' : 'linear'
}

export function chartStyleStrokePattern(chartStyle: ChartStyle | null | undefined): number[] | undefined {
    if (!chartStyle?.lineStyle || chartStyle.lineStyle === 'solid') {
        return undefined
    }
    return LINE_STYLE_DASH_PATTERNS[chartStyle.lineStyle]
}

export function chartStylePointRadius(chartStyle: ChartStyle | null | undefined): number | undefined {
    return chartStyle?.showPoints ? CHART_STYLE_POINT_RADIUS : undefined
}
