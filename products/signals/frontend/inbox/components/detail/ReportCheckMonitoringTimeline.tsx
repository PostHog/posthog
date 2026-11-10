/* eslint-disable react/forbid-dom-props -- positions along the window are data, not a design-scale value */
import { useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { MonitoringTimeline, MonitoringTimelineMeasurement } from './reportCheckObservations'

const TIME_FORMAT = 'MMM D, h:mm A'

function markerLeft(position: number): React.CSSProperties {
    return { left: `${position * 100}%` }
}

function measurementColor(matches: boolean | null): string {
    return matches === true ? 'bg-success' : matches === false ? 'bg-warning' : 'bg-muted'
}

function measurementLabel({ matches, measuredAt }: MonitoringTimelineMeasurement): string {
    const outcome = matches === true ? 'on track' : matches === false ? 'not on track' : 'no result'
    return `Interim check, ${outcome}, ${dayjs(measuredAt).format(TIME_FORMAT)}`
}

/** `startPosition` is where Monitoring began along the strip, when the strip starts earlier than the window. */
export function ReportCheckMonitoringTimeline({
    timeline,
    startPosition = 0,
}: {
    timeline: MonitoringTimeline
    startPosition?: number
}): JSX.Element {
    // One tooltip for the whole strip: separate tooltips on the dots would open alongside the strip's.
    const [overCheck, setOverCheck] = useState(false)
    const checkHover = {
        onMouseEnter: () => setOverCheck(true),
        onMouseLeave: () => setOverCheck(false),
    }
    const elapsed = Math.max(timeline.elapsed - startPosition, 0)

    return (
        <Tooltip title={overCheck ? 'Interim check' : 'Monitoring window'} openOnClick>
            <div
                className="relative py-1.5"
                data-attr="signals-report-check-monitoring-timeline"
                role="group"
                aria-label="Monitoring window"
            >
                <div className="relative h-1.5 w-full rounded-full" style={{ backgroundColor: 'var(--border)' }}>
                    <div
                        className="absolute inset-y-0 rounded-full"
                        style={{
                            left: `${startPosition * 100}%`,
                            width: `${elapsed * 100}%`,
                            backgroundColor: 'var(--border-bold)',
                        }}
                    />
                </div>
                <div className="absolute inset-x-0 top-1/2">
                    {timeline.nextPosition !== null && timeline.nextMeasurementAt && (
                        <span
                            className="absolute flex size-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                            style={markerLeft(timeline.nextPosition)}
                            {...checkHover}
                            role="img"
                            aria-label={`Next interim check, ${dayjs(timeline.nextMeasurementAt).format(TIME_FORMAT)}`}
                        >
                            <span className="size-2 rounded-full border border-primary bg-surface-primary" />
                        </span>
                    )}
                    {timeline.measurements.map((measurement) => (
                        <span
                            key={measurement.id}
                            className="absolute flex size-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                            style={markerLeft(measurement.position)}
                            {...checkHover}
                            role="img"
                            aria-label={measurementLabel(measurement)}
                        >
                            <span className={`size-2 rounded-full ${measurementColor(measurement.matches)}`} />
                        </span>
                    ))}
                </div>
            </div>
        </Tooltip>
    )
}
