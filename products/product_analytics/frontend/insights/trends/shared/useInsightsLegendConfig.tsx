import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import type { ChartLegendConfig } from '@posthog/quill-charts'

import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightLogicProps } from '~/types'

interface UseInsightsLegendConfigOptions {
    insightProps: InsightLogicProps
    inSharedMode?: boolean
}

/** Builds the quill in-chart legend config for trends-family charts. Wires toggle persistence and the
 *  isolate/show-all row menu through trendsDataLogic. Lifecycle and funnel charts build their
 *  legend config inline (they don't read from trendsDataLogic). */
export function useInsightsLegendConfig({
    insightProps,
    inSharedMode = false,
}: UseInsightsLegendConfigOptions): ChartLegendConfig {
    const { canEditInsight } = useValues(insightLogic)
    const { indexedResults, getTrendsHidden, showLegend, legendPosition, resultCustomizationBy } = useValues(
        trendsDataLogic(insightProps)
    )
    const { toggleResultHidden, setResultsHidden } = useActions(trendsDataLogic(insightProps))

    const resultById = useMemo(() => {
        const m = new Map<string, IndexedTrendResult>()
        ;(indexedResults ?? []).forEach((r) => m.set(String(r.id), r))
        return m
    }, [indexedResults])

    const legendInteractive = canEditInsight && !inSharedMode
    const renderItem = useChartLegendSeriesMenu({ surface: 'trends', seriesCount: indexedResults?.length ?? 0 })

    return useMemo<ChartLegendConfig>(() => {
        const hiddenKeys = (indexedResults ?? []).filter((r) => getTrendsHidden(r)).map((r) => String(r.id))
        return {
            show: !!showLegend,
            position: (legendPosition as ChartLegendConfig['position']) ?? 'right',
            interactive: legendInteractive,
            hiddenKeys,
            onToggleSeries: (key: string) => {
                const result = resultById.get(key)
                if (result) {
                    toggleResultHidden(result)
                }
            },
            // Isolating and hide-all rewrite the whole hidden set, so they land as one
            // resultCustomizations update rather than a toggle per series.
            onSetHiddenSeries: setResultsHidden,
            // Hidden state is stored per customization key, and comparing to the previous period puts
            // a series' two rows on one key — so quill has to treat them as one series when it
            // isolates, or the twin row it deliberately leaves visible would read as "not isolated".
            visibilityGroupKey: (key: string) => {
                const result = resultById.get(key)
                return result ? getTrendResultCustomizationKey(resultCustomizationBy, result) : key
            },
            renderItem: legendInteractive ? renderItem : undefined,
        }
    }, [
        indexedResults,
        getTrendsHidden,
        showLegend,
        legendPosition,
        legendInteractive,
        resultById,
        toggleResultHidden,
        setResultsHidden,
        resultCustomizationBy,
        renderItem,
    ])
}
