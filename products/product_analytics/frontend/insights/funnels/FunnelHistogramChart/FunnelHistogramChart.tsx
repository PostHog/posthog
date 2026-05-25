import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart, ValueLabels } from 'lib/hog-charts'
import type { BarChartConfig } from 'lib/hog-charts'
import { humanFriendlyNumber } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { buildFunnelHistogramData } from './funnelHistogramTransforms'

const CHART_CONFIG: BarChartConfig = {
    showGrid: true,
    barCornerRadius: 4,
    yTickFormatter: (value) => humanFriendlyNumber(value),
    tooltip: { placement: 'top' },
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'funnels-histogram-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function FunnelHistogramChart(): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)
    const { histogramGraphData } = useValues(funnelDataLogic(insightProps))
    const { theme: dataColorTheme } = useValues(insightVizDataLogic(insightProps))

    const histogramData = useMemo(
        () => buildFunnelHistogramData(histogramGraphData ?? [], { color: dataColorTheme?.['preset-1'] }),
        [histogramGraphData, dataColorTheme]
    )

    if (!histogramGraphData || histogramGraphData.length === 0) {
        return null
    }

    return (
        <BarChart
            series={histogramData.series}
            labels={histogramData.labels}
            theme={theme}
            config={CHART_CONFIG}
            className="FunnelHistogramChart"
            dataAttr="funnel-histogram"
            onError={handleChartError}
        >
            <ValueLabels
                valueFormatter={(_value, _seriesIndex, dataIndex) => histogramData.barLabels[dataIndex] ?? ''}
            />
        </BarChart>
    )
}
