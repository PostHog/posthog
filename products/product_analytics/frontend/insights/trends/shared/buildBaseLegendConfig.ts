import type { ChartLegendConfig } from '@posthog/quill-charts'

/** Returns the base `{ show, position, interactive }` legend shape shared by all chart types that
 *  build their config inline (lifecycle, funnel). Call sites own the `show` expression — e.g. funnel
 *  gates it on `series.length > 1`. These legends are uncontrolled, so isolating a series and the
 *  row menu's bulk actions work off the chart's own state with nothing to persist. */
export function buildBaseLegendConfig({
    show,
    legendPosition,
    canEditInsight,
    inSharedMode,
    renderItem,
}: {
    show: boolean
    legendPosition: string | null | undefined
    canEditInsight: boolean
    inSharedMode?: boolean
    renderItem?: ChartLegendConfig['renderItem']
}): ChartLegendConfig {
    const interactive = canEditInsight && !inSharedMode
    return {
        show,
        position: (legendPosition ?? 'right') as ChartLegendConfig['position'],
        interactive,
        renderItem: interactive ? renderItem : undefined,
    }
}
