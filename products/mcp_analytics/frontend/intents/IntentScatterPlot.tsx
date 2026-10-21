import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { intentMapLogic } from './intentMapLogic'
import type { IntentScatterMeta } from './intentScatter'
import { IntentScatterTooltip } from './IntentScatterTooltip'

const handleChartError = makeChartErrorHandler('mcp-intent-map-scatter')

/** Topic bubbles at the base zoom; a drag selection pins the axes and loads the intents inside. */
export function IntentScatterPlot(): JSX.Element {
    const { topicSeries, pointSeries, zoom, topicId, mapLoading, mapError, topics } = useValues(intentMapLogic)
    const { setZoom, selectTopic, focusTopic, loadMap } = useActions(intentMapLogic)
    const theme = useChartTheme()
    const [pinned, setPinned] = useState<ScatterAreaSelection | null>(null)

    // Drop the pinned axes when the data space changes so a stale domain never hides the new points.
    useEffect(() => setPinned(zoom), [zoom])

    const config = useMemo<ScatterChartConfig<IntentScatterMeta>>(
        () => ({
            xAxis: { hide: true, domain: pinned?.x },
            yAxis: { hide: true, domain: pinned?.y },
            tooltip: { placement: 'cursor' },
            fillOpacity: 0.65,
            legend: { show: false },
        }),
        [pinned]
    )

    // Bubbles stay visible while narrowing to one topic, so the map keeps its frame of reference.
    const series = useMemo(
        () => [...pointSeries, ...(topicId || zoom ? [] : topicSeries)],
        [pointSeries, topicSeries, topicId, zoom]
    )

    const handlePointClick = (point: ScatterPointDatum<IntentScatterMeta>): void => {
        const meta = point.meta
        if (!meta) {
            return
        }
        if (meta.kind === 'topic') {
            if (meta.topicId) {
                focusTopic(meta.topicId)
            }
            return
        }
        selectTopic(meta.topicId)
    }

    if (mapError && !mapLoading) {
        return (
            <div
                className="flex h-full flex-col items-center justify-center gap-2 text-secondary text-sm"
                data-attr="mcp-intent-map-error"
            >
                <span>The intent map couldn't load.</span>
                <LemonButton size="small" type="secondary" onClick={() => loadMap()}>
                    Try again
                </LemonButton>
            </div>
        )
    }

    if (!mapLoading && topics.length === 0 && pointSeries.length === 0) {
        return (
            <div
                className="flex h-full items-center justify-center text-secondary text-sm"
                data-attr="mcp-intent-map-empty"
            >
                No intent topics yet. Topics appear after the nightly run has embedded and clustered your agents'
                intents.
            </div>
        )
    }

    return (
        <div
            className="flex h-full min-h-[24rem] flex-col"
            onDoubleClick={() => setZoom(null)}
            data-attr="mcp-intent-map-scatter"
        >
            <ScatterChart
                series={series}
                theme={theme}
                config={config}
                dataAttr="mcp-intent-map"
                onPointClick={handlePointClick}
                onAreaSelect={(selection) => setZoom(selection)}
                onError={handleChartError}
                tooltip={({ point }) => <IntentScatterTooltip point={point} />}
            />
        </div>
    )
}
