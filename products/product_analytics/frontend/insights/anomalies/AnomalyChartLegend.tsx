/* eslint-disable react/forbid-dom-props -- the swatches take the chart fill color and opacity */
import { getColorVar } from 'lib/colors'

import {
    ANOMALY_FILL_COLOR_VAR,
    ANOMALY_FILL_OPACITY,
    EARLIER_ANOMALY_FILL_OPACITY,
    RANGE_START_LINE_BORDER,
} from './anomalyChartStyle'

/** Names the marks of every row chart on the Anomalies tab, so the rows do not repeat it. */
export function AnomalyChartLegend(): JSX.Element {
    const fillColor = getColorVar(ANOMALY_FILL_COLOR_VAR)

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-attr="anomalies-tab-chart-legend">
            <span className="flex items-center gap-1">
                <span className="size-3" style={{ backgroundColor: fillColor, opacity: ANOMALY_FILL_OPACITY }} />
                Anomalous in range
            </span>
            <span className="flex items-center gap-1">
                <span
                    className="size-3"
                    style={{ backgroundColor: fillColor, opacity: EARLIER_ANOMALY_FILL_OPACITY }}
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
