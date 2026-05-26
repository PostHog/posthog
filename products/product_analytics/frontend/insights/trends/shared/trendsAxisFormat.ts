import type { YAxisConfig, YFormatterConfig } from 'lib/hog-charts'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

export function trendsFilterToYFormatterConfig(
    trendsFilter: TrendsFilter | null | undefined,
    isPercentStackView: boolean,
    baseCurrency?: CurrencyCode
): YFormatterConfig {
    if (isPercentStackView) {
        // BarChart's percent layout puts the value scale on 0..1, so use the 0..1 formatter.
        return { format: 'percentage_scaled' }
    }
    return {
        format: trendsFilter?.aggregationAxisFormat ?? 'numeric',
        prefix: trendsFilter?.aggregationAxisPrefix,
        suffix: trendsFilter?.aggregationAxisPostfix,
        decimalPlaces: trendsFilter?.decimalPlaces,
        minDecimalPlaces: trendsFilter?.minDecimalPlaces,
        currency: baseCurrency,
    }
}

export function buildTrendsYAxisConfig(
    trendsFilter: TrendsFilter | null | undefined,
    isPercentStackView: boolean,
    baseCurrency: CurrencyCode | undefined,
    extras: { yAxisScaleType?: string | null; showGrid?: boolean } = {}
): YAxisConfig {
    return {
        ...trendsFilterToYFormatterConfig(trendsFilter, isPercentStackView, baseCurrency),
        scale: extras.yAxisScaleType === 'log10' ? 'log' : 'linear',
        showGrid: extras.showGrid,
    }
}
