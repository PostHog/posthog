import { type ErrorInfo, useMemo } from 'react'

import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    type PointClickData,
    type TooltipContext,
} from '@posthog/quill-charts'

import {
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
} from '../shared/funnelBarHorizontalShared'

const BAR_CORNER_RADIUS = 4

interface SingleStepBarProps {
    stepData: FunnelBarHorizontalStepData
    theme: ChartTheme
    interactive: boolean
    onSegmentClick: (meta: FunnelBarHorizontalSegmentMeta) => void
    renderTooltip: (ctx: TooltipContext<FunnelBarHorizontalSegmentMeta>) => JSX.Element | null
    onError: (error: Error, info: ErrorInfo) => void
    /** Tailwind height of the bar track. Compare mode stacks two bars per step, so it passes a
     *  shorter height to keep the step row close to a single bar's footprint. */
    heightClassName?: string
}

const CHART_CONFIG: BarChartConfig = {
    barLayout: 'stacked',
    axisOrientation: 'horizontal',
    hideXAxis: true,
    hideYAxis: true,
    showGrid: false,
    animateHover: true,
    margins: { top: 0, right: 0, bottom: 0, left: 0 },
    tooltip: { placement: 'cursor' },
    bars: {
        cornerRadius: BAR_CORNER_RADIUS,
        bandPadding: 0,
        minBandSize: 0,
        valueDomain: FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
        roundStackEnds: true,
    },
}

export function SingleStepBar({
    stepData,
    theme,
    interactive,
    onSegmentClick,
    renderTooltip,
    onError,
    heightClassName = 'h-8',
}: SingleStepBarProps): JSX.Element {
    const onPointClick = useMemo(
        () =>
            interactive
                ? (clickData: PointClickData<FunnelBarHorizontalSegmentMeta>): void => {
                      const meta = clickData.series.meta
                      if (meta) {
                          onSegmentClick(meta)
                      }
                  }
                : undefined,
        [interactive, onSegmentClick]
    )

    return (
        <div className={`flex flex-col ${heightClassName} my-1`}>
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
