import type { ChartStyle } from '~/queries/schema/schema-general'

export function chartStyleCurve(chartStyle: ChartStyle | null | undefined): 'linear' | 'monotone' | undefined {
    if (!chartStyle?.curve) {
        return undefined
    }
    return chartStyle.curve === 'smooth' ? 'monotone' : 'linear'
}
