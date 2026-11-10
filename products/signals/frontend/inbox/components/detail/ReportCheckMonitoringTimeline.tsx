import { useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type { MonitoringTimeline } from './reportCheckObservations'

function markerLeft(position: number): React.CSSProperties {
    return { left: `${position * 100}%` }
}

function measurementColor(matches: boolean | null): string {
    return matches === true ? 'bg-success' : matches === false ? 'bg-warning' : 'bg-muted'
}

export function ReportCheckMonitoringTimeline({ timeline }: { timeline: MonitoringTimeline }): JSX.Element {
    // One tooltip for the whole strip: separate tooltips on the dots would open alongside the strip's.
    const [overCheck, setOverCheck] = useState(false)
    const checkHover = {
        onMouseEnter: () => setOverCheck(true),
        onMouseLeave: () => setOverCheck(false),
    }

    return (
        <Tooltip title={overCheck ? 'Interim check' : 'Monitoring window'} openOnClick>
            <div
                className="relative flex py-1.5"
                data-attr="signals-report-check-monitoring-timeline"
                role="group"
                aria-label="Monitoring window"
            >
                <LemonProgress
                    percent={timeline.elapsed * 100}
                    bgColor="var(--border)"
                    strokeColor="var(--border-bold)"
                    smoothing={false}
                />
                <div className="absolute inset-x-0 top-1/2">
                    {timeline.nextPosition !== null && (
                        <span
                            className="absolute flex size-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                            // Positions along the window are data, not a design-scale value.
                            // eslint-disable-next-line react/forbid-dom-props
                            style={markerLeft(timeline.nextPosition)}
                            {...checkHover}
                            role="img"
                            aria-label="Interim check"
                        >
                            <span className="size-2 rounded-full border border-primary bg-surface-primary" />
                        </span>
                    )}
                    {timeline.measurements.map((measurement) => (
                        <span
                            key={measurement.id}
                            className="absolute flex size-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={markerLeft(measurement.position)}
                            {...checkHover}
                            role="img"
                            aria-label="Interim check"
                        >
                            <span className={`size-2 rounded-full ${measurementColor(measurement.matches)}`} />
                        </span>
                    ))}
                </div>
            </div>
        </Tooltip>
    )
}
