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
    const labelsByDay = new Map<string, string[]>()
    for (const { day, label } of markers) {
        labelsByDay.set(day, [...(labelsByDay.get(day) ?? []), label])
    }
    const placed = [...labelsByDay]
        .flatMap(([day, labels]) => {
            const x = scales.x(day)
            return x === undefined || x < dimensions.plotLeft || x > dimensions.plotLeft + dimensions.plotWidth
                ? []
                : [{ day, labels, x }]
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
            {groups.map((group) => (
                <div
                    key={placed[group[0]].day}
                    className="absolute -translate-x-1/2 -translate-y-full whitespace-nowrap pb-0.5 text-[11px] font-medium text-secondary"
                    style={{ left: placed[group[0]].x, top: dimensions.plotTop }}
                >
                    {[...new Set(group.flatMap((index) => placed[index].labels))].join(' · ')}
                </div>
            ))}
        </>
    )
}
