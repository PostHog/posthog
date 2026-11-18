import { Fragment } from 'react'

import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

// Expanded-row view of one emission's datapoint and resource attributes, shared by the
// metrics Samples panel and the tracing drawer's Metrics tab.
export function SampleAttributes({ sample }: { sample: _MetricEventSampleApi }): JSX.Element {
    const entries = [...Object.entries(sample.attributes), ...Object.entries(sample.resource_attributes)]
    if (!entries.length) {
        return <div className="text-secondary text-xs p-2">No attributes on this emission.</div>
    }
    return (
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 p-2 text-xs">
            {/* Index-keyed: the same attribute key can appear in both the datapoint and resource maps. */}
            {entries.map(([key, value], index) => (
                <Fragment key={index}>
                    <span className="text-secondary font-mono">{key}</span>
                    <span className="font-mono break-all">{value}</span>
                </Fragment>
            ))}
        </div>
    )
}
