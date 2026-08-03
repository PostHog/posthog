import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { MetricsSeriesChart } from './MetricsSeriesChart'

const START = '2026-07-30T12:00:00Z'

const meta: Meta<typeof MetricsSeriesChart> = {
    title: 'Metrics/MetricsSeriesChart',
    component: MetricsSeriesChart,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2026-08-01 12:00:00',
    },
    // The component fills its parent (`h-full w-full`), mirroring how the Viewer and the
    // dashboard tile mount it, so the story supplies the sized box rather than a className.
    decorators: [
        (Story) => (
            <div className="w-[820px] h-[360px] p-3 border rounded bg-surface-primary">
                <Story />
            </div>
        ),
    ],
    args: {
        fallbackName: 'http.server.requests',
    },
}

export default meta

type Story = StoryObj<typeof MetricsSeriesChart>

export const SingleSeries: Story = {
    args: {
        series: [series({}, wave(48, 120, 40, 0))],
    },
}

export const MultipleSeriesWithLegend: Story = {
    args: {
        series: [
            series({ service: 'checkout' }, wave(48, 120, 40, 0)),
            series({ service: 'billing' }, wave(48, 70, 25, 2)),
            series({ service: 'ingestion' }, wave(48, 200, 80, 4)),
        ],
    },
}

export const WithTracedExemplars: Story = {
    args: {
        series: [series({}, wave(48, 120, 40, 0))],
        // Deliberately off-bucket timestamps: the dots interpolate between buckets rather than
        // snapping to one, so an emission mid-bucket lands mid-bucket.
        exemplars: [4.5, 11.2, 11.9, 26.3, 40.7].map((hoursIn) => ({
            timeMs: dayjs(START)
                .add(hoursIn * 60, 'minutes')
                .valueOf(),
            onClick: () => {},
        })),
    },
}

export const WithGapBuckets: Story = {
    args: {
        series: [
            series(
                { service: 'checkout' },
                wave(48, 120, 40, 0).map((v, i) => (i > 20 && i < 26 ? null : v))
            ),
        ],
    },
}

function series(
    labels: Record<string, string>,
    values: (number | null)[]
): Parameters<typeof MetricsSeriesChart>[0]['series'][number] {
    return {
        labels,
        points: values.map((value, index) => ({
            time: dayjs(START).add(index, 'hour').toISOString(),
            value,
        })),
    }
}

/** Deterministic sine wave so snapshots don't drift between runs. */
function wave(count: number, mean: number, amplitude: number, phase: number): number[] {
    return Array.from({ length: count }, (_, i) => Math.round(mean + amplitude * Math.sin(i / 4 + phase)))
}
