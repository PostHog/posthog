import { type ErrorInfo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type PointClickData,
    type TooltipContext,
} from 'lib/hog-charts'

import {
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
} from './funnelBarHorizontalTransforms'

interface SingleStepBarProps {
    stepData: FunnelBarHorizontalStepData
    theme: ChartTheme
    interactive: boolean
    onSegmentClick: (meta: FunnelBarHorizontalSegmentMeta) => void
    renderTooltip: (ctx: TooltipContext<FunnelBarHorizontalSegmentMeta>) => JSX.Element | null
    onError: (error: Error, info: ErrorInfo) => void
}

const CHART_CONFIG: BarChartConfig = {
    barLayout: 'stacked',
    axisOrientation: 'horizontal',
    hideXAxis: true,
    hideYAxis: true,
    showGrid: false,
    animateHover: true,
    margins: { top: 0, right: 0, bottom: 0, left: 0 },
    tooltip: { placement: 'top' },
    bars: {
        cornerRadius: 4,
        bandPadding: 0,
        minBandSize: 0,
        valueDomain: FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    },
}

export function SingleStepBar({
    stepData,
    theme,
    interactive,
    onSegmentClick,
    renderTooltip,
    onError,
}: SingleStepBarProps): JSX.Element {
    const onPointClick = interactive
        ? (clickData: PointClickData<FunnelBarHorizontalSegmentMeta>): void => {
              const meta = clickData.series.meta
              if (meta) {
                  onSegmentClick(meta)
              }
          }
        : undefined

    return (
        <div className="flex flex-col h-8 my-1">
            <BarChart<FunnelBarHorizontalSegmentMeta>
                series={stepData.series}
                labels={[stepData.label]}
                theme={theme}
                config={CHART_CONFIG}
                tooltip={renderTooltip}
                onPointClick={onPointClick}
                onError={onError}
            />
        </div>
    )
}
