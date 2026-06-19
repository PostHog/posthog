import { useActions, useValues } from 'kea'
import { useMemo, type ReactNode } from 'react'

import type { ChartLegendConfig, LegendItem } from '@posthog/quill-charts'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightLogicProps } from '~/types'

import { TrendsLegendItemContextMenu } from './TrendsLegendItemContextMenu'

interface UseTrendsLegendConfigOptions {
    insightProps: InsightLogicProps
    inSharedMode?: boolean
}

/** Builds the quill in-chart legend config shared by the trends-family charts (line/area/cumulative,
 *  and bar next). Wires toggle persistence + the isolate/show-all context menu through trendsDataLogic
 *  so every trends chart renders one consistent legend. Returns `undefined` when the quill-legend flag
 *  is off, so callers fall back to the legacy side legend and skip pre-stripping hidden series. */
export function useTrendsLegendConfig({
    insightProps,
    inSharedMode = false,
}: UseTrendsLegendConfigOptions): ChartLegendConfig | undefined {
    const { featureFlags } = useValues(featureFlagLogic)
    const quillLegendEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]
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

    return useMemo<ChartLegendConfig | undefined>(() => {
        if (!quillLegendEnabled) {
            return undefined
        }
        const hiddenKeys = (indexedResults ?? []).filter((r) => getTrendsHidden(r)).map((r) => String(r.id))
        const showContextMenu = legendInteractive && legendSeriesIsolationMenuEligible
        return {
            show: !!showLegend,
            position: (legendPosition as ChartLegendConfig['position']) ?? 'bottom',
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
        quillLegendEnabled,
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
