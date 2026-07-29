import type { ChartLegendConfig } from '@posthog/quill-charts'

/** Returns the base `{ show, position, interactive }` legend shape shared by all chart types that
 *  build their config inline (lifecycle, funnel). Call sites own the `show` expression — e.g. funnel
 *  gates it on `series.length > 1`. */
export function buildBaseLegendConfig({
    show,
    legendPosition,
    canEditInsight,
}: {
    show: boolean
    legendPosition: string | null | undefined
    canEditInsight: boolean
}): ChartLegendConfig {
    return {
        show,
        position: (legendPosition ?? 'right') as ChartLegendConfig['position'],
        // Interactive on shared and exported views too: these charts keep their toggled-off series
        // in local state, so hiding one never needs to write back to the insight.
        interactive: canEditInsight,
    }
}
