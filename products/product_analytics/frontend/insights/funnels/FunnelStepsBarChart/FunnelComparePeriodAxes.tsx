/* eslint-disable react/forbid-dom-props -- tick positions come from the chart's d3 scales */
import { useChartLayout } from '@posthog/quill-charts'

import { visibleComparePeriodTicks, type FunnelComparePeriodShares } from './funnelStepsBarTransforms'

/** Horizontal gap between the plot edge and the tick labels — matches the built-in axis. */
const TICK_GAP_PX = 8
/** Built-in AxisLabels default, used when the theme doesn't provide an axis label color. */
const AXIS_LABEL_FALLBACK_COLOR = 'rgba(0, 0, 0, 0.5)'

/** Replaces the funnel's built-in percent axis in compare mode: each period gets its own 0–100%
 *  axis — current period on the left, previous on the right — compressed so its 100% sits at that
 *  period's entry level (its share of the larger period's entrants). The bars stay volume-true;
 *  the axes give each period's first step a 100% reading on its own side.
 *
 *  Render as a `FunnelChart` child together with `hideValueAxis: true` and a right margin wide
 *  enough for the labels. */
export function FunnelComparePeriodAxes({ shares }: { shares: FunnelComparePeriodShares }): JSX.Element {
    const { scales, theme } = useChartLayout()
    // The primary scale's own tick values (height-adaptive), so an uncompressed period axis lines
    // up with the grid exactly like the built-in axis it replaces.
    const percents = scales.yTicks()
    const color = theme.axisColor ?? AXIS_LABEL_FALLBACK_COLOR

    return (
        <>
            <PeriodAxis side="left" share={shares.current} percents={percents} color={color} />
            <PeriodAxis side="right" share={shares.previous} percents={percents} color={color} />
        </>
    )
}

function PeriodAxis({
    side,
    share,
    percents,
    color,
}: {
    side: 'left' | 'right'
    share: number
    percents: number[]
    color: string
}): JSX.Element {
    const { scales, dimensions } = useChartLayout()
    const toPixel = (percent: number): number => scales.y(share * percent)
    const plotBottom = dimensions.plotTop + dimensions.plotHeight
    const edge =
        side === 'left'
            ? { right: dimensions.width - dimensions.plotLeft + TICK_GAP_PX }
            : { left: dimensions.plotLeft + dimensions.plotWidth + TICK_GAP_PX }

    return (
        <>
            {visibleComparePeriodTicks(percents, toPixel).map((percent) => {
                const y = toPixel(percent)
                if (!isFinite(y) || y < dimensions.plotTop - 1 || y > plotBottom + 1) {
                    return null
                }
                return (
                    <div
                        key={percent}
                        data-attr={`funnel-compare-period-axis-${side}`}
                        className="pointer-events-none absolute whitespace-nowrap text-xs"
                        style={{ ...edge, top: y, transform: 'translateY(-50%)', color }}
                    >
                        {Math.round(percent)}%
                    </div>
                )
            })}
        </>
    )
}
