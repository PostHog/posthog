import { Meta, StoryObj } from '@storybook/react'

import type { LogsSeriesBandBucketApi } from 'products/logs/frontend/generated/api.schemas'

import { AnomalyBandChart } from './AnomalyBandChart'

const BUCKET_MINUTES = 60
const BUCKETS = 72
const FIRST_BUCKET = Date.parse('2026-08-03T04:00:00Z')

/** Buckets that exercise every state the chart draws: a banded stretch, an out-of-band spike and
 *  drop against it, and a trailing learning stretch where the band has to break. */
function buildBuckets(): LogsSeriesBandBucketApi[] {
    return Array.from({ length: BUCKETS }, (_, index) => {
        const time = new Date(FIRST_BUCKET + index * BUCKET_MINUTES * 60_000).toISOString()
        // A slow sine keeps the baseline uneven without a random source.
        const typical = Math.round(400 + 120 * Math.sin(index / 5))
        const banded = index < BUCKETS - 8
        const observed = index === 24 ? typical * 4 : index === 44 ? Math.round(typical * 0.1) : typical

        return {
            time,
            observed,
            lower: banded ? Math.round(typical * 0.6) : null,
            upper: banded ? Math.round(typical * 1.4) : null,
        }
    })
}

const meta: Meta<typeof AnomalyBandChart> = {
    title: 'Logs/AnomalyBandChart',
    component: AnomalyBandChart,
    args: {
        buckets: buildBuckets(),
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-08-06',
        // The line and band paint asynchronously (ResizeObserver → rAF); chromium alone keeps the
        // snapshot stable.
        testOptions: { snapshotBrowsers: ['chromium'], waitForSelector: 'canvas[aria-label]' },
    },
    render: (args) => (
        <div className="w-[720px] rounded border bg-surface-primary p-3">
            <AnomalyBandChart {...args} />
        </div>
    ),
}

export default meta

/** What `LogsAnomalies` renders per series: observed volume against the time-of-week band, with
 *  out-of-band buckets marked and the unbanded tail left as a gap. */
export const ObservedVsExpected: StoryObj<typeof AnomalyBandChart> = {}
