import type { ChartLegendConfig } from '@posthog/quill-charts'

/** Returns the base `{ show, position, interactive }` legend shape shared by all chart types that
 *  build their config inline (lifecycle, funnel). Call sites own the `show` expression — e.g. funnel
 *  gates it on `series.length > 1`. */
export function buildBaseLegendConfig({
    show,
    legendPosition,
    canEditInsight,
    inSharedMode,
}: {
    show: boolean
    legendPosition: string | null | undefined
    canEditInsight: boolean
    inSharedMode?: boolean
}): ChartLegendConfig {
    return {
        show,
        position: (legendPosition ?? 'right') as ChartLegendConfig['position'],
        interactive: canEditInsight && !inSharedMode,
    }
}
