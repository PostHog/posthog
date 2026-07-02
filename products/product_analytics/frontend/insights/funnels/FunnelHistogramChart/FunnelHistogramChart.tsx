import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, type ErrorInfo } from 'react'

import { BarChart, ValueLabels } from '@posthog/quill-charts'
import type { BarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { hexToRGBA } from 'lib/utils/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { buildFunnelHistogramData } from './funnelHistogramTransforms'

const CHART_CONFIG: BarChartConfig = {
    showGrid: true,
    bars: { cornerRadius: 4 },
    yTickFormatter: (value) => humanFriendlyNumber(value),
    // Value labels already show bucket counts; tooltip would just duplicate them.
    tooltip: { enabled: false },
}

// Matches the trends compare convention of dimming the previous period to 50% alpha.
const PREVIOUS_PERIOD_ALPHA = 0.5

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-histogram-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function FunnelHistogramChart(): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)
    const { histogramGraphData, histogramGraphDataPrevious } = useValues(funnelDataLogic(insightProps))
    const { theme: dataColorTheme } = useValues(insightVizDataLogic(insightProps))

    const currentColor = dataColorTheme?.['preset-1']
    const isComparing = !!histogramGraphDataPrevious

    const histogramData = useMemo(
        () =>
            buildFunnelHistogramData(histogramGraphData ?? [], {
                color: currentColor,
                previous: histogramGraphDataPrevious
                    ? {
                          data: histogramGraphDataPrevious,
                          color: currentColor ? hexToRGBA(currentColor, PREVIOUS_PERIOD_ALPHA) : undefined,
                      }
                    : undefined,
            }),
        [histogramGraphData, histogramGraphDataPrevious, currentColor]
    )

    const config = useChartConfig<BarChartConfig>(
        () => (isComparing ? { ...CHART_CONFIG, barLayout: 'grouped' } : CHART_CONFIG),
        [isComparing]
    )

    if (!histogramGraphData || histogramGraphData.length === 0) {
        return null
    }

    return (
        <BarChart
            series={histogramData.series}
            labels={histogramData.labels}
            theme={theme}
            config={config}
            className="FunnelHistogramChart"
            dataAttr="funnel-histogram"
            onError={handleChartError}
        >
            {/* Per-bar percentage labels only read cleanly with a single series; the grouped
                compare view relies on tooltips (which label each period) instead. */}
            {!isComparing && (
                <ValueLabels
                    valueFormatter={(_value, _seriesIndex, dataIndex) => histogramData.barLabels[dataIndex] ?? ''}
                />
            )}
        </BarChart>
    )
}
