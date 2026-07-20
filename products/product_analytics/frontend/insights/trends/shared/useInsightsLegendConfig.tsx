import { useActions, useValues } from 'kea'
import { useMemo, type ReactNode } from 'react'

import type { ChartLegendConfig, LegendItem } from '@posthog/quill-charts'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightLogicProps } from '~/types'

import { TrendsLegendItemContextMenu } from './TrendsLegendItemContextMenu'

interface UseInsightsLegendConfigOptions {
    insightProps: InsightLogicProps
    inSharedMode?: boolean
}

/** Builds the quill in-chart legend config for trends-family charts. Wires toggle persistence and the
 *  isolate/show-all context menu through trendsDataLogic. Lifecycle and funnel charts build their
 *  legend config inline (they don't read from trendsDataLogic). */
export function useInsightsLegendConfig({
    insightProps,
    inSharedMode = false,
}: UseInsightsLegendConfigOptions): ChartLegendConfig {
    const { canEditInsight } = useValues(insightLogic)
    const { indexedResults, getTrendsHidden, showLegend, legendPosition, legendSeriesIsolationMenuEligible } =
        useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden } = useActions(trendsDataLogic(insightProps))

    const resultById = useMemo(() => {
        const m = new Map<string, IndexedTrendResult>()
        ;(indexedResults ?? []).forEach((r) => m.set(String(r.id), r))
        return m
    }, [indexedResults])

    const legendInteractive = canEditInsight && !inSharedMode

    return useMemo<ChartLegendConfig>(() => {
        const hiddenKeys = (indexedResults ?? []).filter((r) => getTrendsHidden(r)).map((r) => String(r.id))
        const showContextMenu = legendInteractive && legendSeriesIsolationMenuEligible
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
            renderItem: showContextMenu
                ? (node: ReactNode, item: LegendItem) => {
                      const result = resultById.get(item.key)
                      if (!result) {
                          return node
                      }
                      return (
                          <TrendsLegendItemContextMenu insightProps={insightProps} item={result}>
                              {node}
                          </TrendsLegendItemContextMenu>
                      )
                  }
                : undefined,
        }
    }, [
        indexedResults,
        getTrendsHidden,
        showLegend,
        legendPosition,
        legendInteractive,
        legendSeriesIsolationMenuEligible,
        resultById,
        toggleResultHidden,
        insightProps,
    ])
}
