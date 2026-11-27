import { ReferenceLine, useChartLayout } from '@posthog/quill-charts'

import { healthLabelGroups } from './healthChartLabels'

export const HEALTH_CHART_MARKER_MARGIN = 24
// Wider than the longest marker label at 11px.
const MARKER_LABEL_WIDTH = 90

export interface HealthChartDayMarker {
    day: string
    label: string
}

/** Labels sit centered above the plot, where no data is drawn. */
export function HealthChartDayMarkers({ markers }: { markers: HealthChartDayMarker[] }): JSX.Element {
    const { scales, dimensions } = useChartLayout()
    const placed = [...new Map(markers.map((marker) => [marker.day, marker])).values()]
        .flatMap((marker) => {
            const x = scales.x(marker.day)
            return x === undefined || x < dimensions.plotLeft || x > dimensions.plotLeft + dimensions.plotWidth
                ? []
                : [{ ...marker, x }]
        })
        .sort((a, b) => a.x - b.x)
    const groups = healthLabelGroups(
        placed.map(({ x }) => x),
        MARKER_LABEL_WIDTH
    )

    return (
        <>
            {placed.map(({ day }) => (
                <ReferenceLine key={day} value={day} orientation="vertical" variant="marker" />
            ))}
            {groups.map(([first]) => (
                <div
                    key={placed[first].day}
                    className="absolute -translate-x-1/2 -translate-y-full whitespace-nowrap pb-0.5 text-[11px] font-medium text-secondary"
                    style={{ left: placed[first].x, top: dimensions.plotTop }}
                >
                    {placed[first].label}
                </div>
            ))}
        </>
    )
}
