/* eslint-disable react/forbid-dom-props -- chart scales determine label positions */
import { ReferenceLines, useChartLayout, type ReferenceLineProps } from '@posthog/quill-charts'

export function ReportChartMarkers({ markers }: { markers: ReferenceLineProps[] }): JSX.Element {
    const { scales, dimensions } = useChartLayout()

    return (
        <>
            <ReferenceLines
                lines={markers.map((marker) =>
                    marker.labelPosition === 'start' ? { ...marker, label: undefined } : marker
                )}
            />
            {markers.map((marker) => {
                if (marker.labelPosition !== 'start' || typeof marker.value !== 'string' || !marker.label) {
                    return null
                }
                const left = scales.x(marker.value)
                if (
                    left == null ||
                    !Number.isFinite(left) ||
                    left < dimensions.plotLeft ||
                    left > dimensions.plotLeft + dimensions.plotWidth
                ) {
                    return null
                }
                return (
                    <span
                        key={marker.value}
                        data-attr="report-chart-marker-label"
                        className="absolute -translate-x-1/2 -translate-y-full whitespace-nowrap pb-1 text-xs text-secondary"
                        style={{ left, top: dimensions.plotTop }}
                    >
                        {marker.label}
                    </span>
                )
            })}
        </>
    )
}
