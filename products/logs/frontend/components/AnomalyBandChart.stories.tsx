import { Meta, StoryObj } from '@storybook/react'

import type { LogsAnomalyScanBucketApi } from 'products/logs/frontend/generated/api.schemas'

import { AnomalyBandChart } from './AnomalyBandChart'

const BUCKET_MINUTES = 5
const BUCKETS = 72
const FIRST_BUCKET = Date.parse('2026-08-06T04:00:00Z')

/** Buckets that exercise every state the chart draws: a learned band, an anomalous spike and drop
 *  against it, a silence, and a trailing unscored stretch where the band has to break. */
function buildBuckets(): LogsAnomalyScanBucketApi[] {
    return Array.from({ length: BUCKETS }, (_, index) => {
        const time = new Date(FIRST_BUCKET + index * BUCKET_MINUTES * 60_000).toISOString()
        // A slow sine keeps the baseline uneven without a random source.
        const expected = Math.round(400 + 120 * Math.sin(index / 5))
        const scored = index < BUCKETS - 8
        const verdict = index === 24 ? 'spike' : index === 44 ? 'drop' : index === 52 ? 'silence' : null
        const observed =
            verdict === 'spike'
                ? expected * 4
                : verdict === 'drop'
                  ? Math.round(expected * 0.2)
                  : verdict === 'silence'
                    ? 0
                    : expected

        return {
            time,
            observed,
            expected: scored ? expected : null,
            lower: scored ? Math.round(expected * 0.6) : null,
            upper: scored ? Math.round(expected * 1.4) : null,
            stage: scored ? 'mature' : null,
            verdict,
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

/** What `LogsAnomalies` renders per severity: observed volume against the learned band, with the
 *  anomalous buckets marked and the unscored tail left as a gap. */
export const ObservedVsExpected: StoryObj<typeof AnomalyBandChart> = {}
