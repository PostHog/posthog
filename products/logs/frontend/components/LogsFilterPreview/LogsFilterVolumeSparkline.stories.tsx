import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { OTHER_BREAKDOWN_VALUE } from 'products/logs/frontend/sparklineOtherBreakdown'

import { LogsFilterPreviewPoint } from './logsFilterVolumePreview'
import { LogsFilterVolumeSparkline, LogsFilterVolumeSparklineProps } from './LogsFilterVolumeSparkline'

const BUCKET_MINUTES = 30
const BUCKETS = 48
const FIRST_BUCKET = Date.parse('2026-08-04T00:00:00Z')

/** Deterministic per-service shape: a steady baseline plus one afternoon spike, so the rate-limit
 *  line has something to cross. */
const SERVICE_PROFILES: { service: string; baseline: number; spike: number }[] = [
    { service: 'posthog-web', baseline: 900, spike: 3200 },
    { service: 'capture', baseline: 600, spike: 900 },
    { service: 'cdp-events-consumer', baseline: 240, spike: 240 },
    { service: OTHER_BREAKDOWN_VALUE, baseline: 180, spike: 320 },
]

function buildPoints(): LogsFilterPreviewPoint[] {
    const points: LogsFilterPreviewPoint[] = []
    for (let bucket = 0; bucket < BUCKETS; bucket++) {
        const time = new Date(FIRST_BUCKET + bucket * BUCKET_MINUTES * 60_000).toISOString()
        const spiking = bucket >= 28 && bucket <= 32
        for (const { service, baseline, spike } of SERVICE_PROFILES) {
            // A slow sine wave keeps the bars uneven without a random source.
            const wave = 1 + 0.35 * Math.sin(bucket / 4)
            const count = Math.round((spiking ? spike : baseline) * wave)
            points.push({ time, service, count, bytes_uncompressed: count * 420 })
        }
    }
    return points
}

const FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: 'posthog-web' } as never],
}

const meta: Meta<LogsFilterVolumeSparklineProps> = {
    title: 'Logs/LogsFilterVolumeSparkline',
    component: LogsFilterVolumeSparkline,
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/logs/sparkline': () => [200, buildPoints()],
            },
        }),
    ],
    args: {
        filterGroup: FILTER_GROUP,
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-08-05',
        // Bars paint asynchronously (ResizeObserver → rAF); chromium alone keeps the snapshot stable.
        testOptions: { snapshotBrowsers: ['chromium'], waitForSelector: 'canvas[aria-label]' },
    },
    render: (args) => (
        <div className="w-[720px]">
            <LogsFilterVolumeSparkline {...args} />
        </div>
    ),
}

export default meta

type Story = StoryObj<LogsFilterVolumeSparklineProps>

/** What the drop-rule and retention editors render: stacked volume per service, no threshold. */
export const VolumeByService: Story = {
    args: {
        previewKey: 'storybook-volume-by-service',
        metric: 'count',
    },
}

/** The rate-limit case the sampling editor renders: bytes per bucket against a per-second limit
 *  projected onto the bucket width, the way `LogsSamplingForm` does it. */
export const WithRateLimitThreshold: Story = {
    args: {
        previewKey: 'storybook-volume-rate-limit',
        metric: 'bytes',
        buildGoalLines: ({ bucketSeconds }) => [
            {
                // 1 KB/s × 1000 = bytes/s, × bucket width = bytes/bucket.
                value: 1000 * bucketSeconds,
                color: 'var(--danger)',
                label: 'Rate limit (1 KB/s)',
                displayLabel: true,
            },
        ],
    },
}
