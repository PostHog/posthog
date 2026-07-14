import type { TooltipContext } from '@posthog/quill-charts'

import type { TrendsSeriesMeta } from './trendsSeriesMeta'

export function canShowTrendsTotal(
    seriesData: TooltipContext<TrendsSeriesMeta>['seriesData'],
    {
        isStickiness,
        isPercentStackView,
        formula,
    }: {
        isStickiness: boolean
        isPercentStackView: boolean
        formula?: string | null
    }
): boolean {
    if (isPercentStackView || isStickiness || formula) {
        return false
    }
    if (seriesData.some((s) => s.series.meta?.compare_label !== undefined)) {
        return false
    }
    return seriesData.every((s) => {
        const math = s.series.meta?.action?.math
        return !math || math === 'total' || math === 'sum'
    })
}
