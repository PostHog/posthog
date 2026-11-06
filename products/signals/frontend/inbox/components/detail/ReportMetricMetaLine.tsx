import { Fragment, type ReactNode } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

export interface ReportMetricMetaSegment {
    key: string
    node: ReactNode
}

/** When the saved snapshot was measured; empty when the metric has no snapshot time. */
export function measuredMetaSegments(metric: ReportMetricApi): ReportMetricMetaSegment[] {
    if (!metric.value_at) {
        return []
    }

    return [
        {
            key: 'measured',
            node: (
                <span>
                    Measured <TZLabel time={metric.value_at} />
                </span>
            ),
        },
    ]
}

/** The small mono line under an observation figure, its segments joined by a middle dot. */
export function ReportMetricMetaLine({ segments }: { segments: ReportMetricMetaSegment[] }): JSX.Element | null {
    if (segments.length === 0) {
        return null
    }

    // Plain inline flow, not a flex row: the line then wraps between words instead of leaving a
    // separator stranded at the end of a line.
    return (
        <div className="font-mono text-[11px] text-tertiary">
            {segments.map((segment, index) => (
                <Fragment key={segment.key}>
                    {index > 0 ? <span aria-hidden> · </span> : null}
                    {segment.node}
                </Fragment>
            ))}
        </div>
    )
}
