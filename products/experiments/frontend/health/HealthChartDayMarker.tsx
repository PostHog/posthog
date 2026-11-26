import { ReferenceLine, useChartLayout } from '@posthog/quill-charts'

export const HEALTH_CHART_MARKER_MARGIN = 24

/** A dashed line on one day of a time-series chart, with its label centered above the plot, where no data is drawn. */
export function HealthChartDayMarker({ day, label }: { day: string; label: string }): JSX.Element | null {
    const { scales, dimensions } = useChartLayout()
    const x = scales.x(day)
    if (x === undefined || x < dimensions.plotLeft || x > dimensions.plotLeft + dimensions.plotWidth) {
        return null
    }
    return (
        <>
            <ReferenceLine value={day} orientation="vertical" variant="marker" />
            <div
                className="absolute -translate-x-1/2 -translate-y-full whitespace-nowrap pb-0.5 text-[11px] font-medium text-secondary"
                style={{ left: x, top: dimensions.plotTop }}
            >
                {label}
            </div>
        </>
    )
}
