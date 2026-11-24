/* eslint-disable react/forbid-dom-props -- the swatches take the chart fill color, opacity and point size */
import { getColorVar } from 'lib/colors'

import {
    ANOMALY_FILL_COLOR_VAR,
    ANOMALY_FILL_OPACITY,
    ANOMALY_POINT_RADIUS,
    EARLIER_ANOMALY_FILL_OPACITY,
    RANGE_START_LINE_BORDER,
    earlierAnomalyPointColor,
} from './anomalyChartStyle'

function AnomalySwatch({
    fillColor,
    fillOpacity,
    pointColor,
}: {
    fillColor: string
    fillOpacity: number
    pointColor: string
}): JSX.Element {
    const diameter = ANOMALY_POINT_RADIUS * 2
    return (
        <span className="relative flex size-3 items-center justify-center">
            <span className="absolute inset-0" style={{ backgroundColor: fillColor, opacity: fillOpacity }} />
            <span
                className="relative rounded-full"
                style={{ width: diameter, height: diameter, backgroundColor: pointColor }}
            />
        </span>
    )
}

/** Names the marks of every row chart on the Anomalies tab, so the rows do not repeat it. */
export function AnomalyChartLegend(): JSX.Element {
    const fillColor = getColorVar(ANOMALY_FILL_COLOR_VAR)

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-attr="anomalies-tab-chart-legend">
            <span className="flex items-center gap-1">
                <AnomalySwatch fillColor={fillColor} fillOpacity={ANOMALY_FILL_OPACITY} pointColor={fillColor} />
                Anomalous in range
            </span>
            <span className="flex items-center gap-1">
                <AnomalySwatch
                    fillColor={fillColor}
                    fillOpacity={EARLIER_ANOMALY_FILL_OPACITY}
                    pointColor={earlierAnomalyPointColor(fillColor)}
                />
                Anomalous earlier
            </span>
            <span className="flex items-center gap-1">
                <span className="h-3" style={{ borderLeft: RANGE_START_LINE_BORDER }} />
                Range start
            </span>
        </div>
    )
}
