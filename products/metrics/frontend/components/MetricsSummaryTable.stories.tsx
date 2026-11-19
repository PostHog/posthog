import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { _MetricNameApi } from '../generated/api.schemas'
import { MetricsSummaryTable } from './MetricsSummaryTable'

const METRICS: _MetricNameApi[] = [
    {
        name: 'http.server.request.duration',
        metric_type: 'histogram',
        unit: 'ms',
        last_seen: '2026-10-05T11:59:30Z',
        series_count: 1240,
        tag_key_count: 7,
    },
    {
        name: 'process.cpu.utilization',
        metric_type: 'gauge',
        unit: '1',
        last_seen: '2026-10-05T11:58:00Z',
        series_count: 86,
        tag_key_count: 4,
    },
    {
        name: 'queue.messages.processed',
        metric_type: 'sum',
        unit: '',
        last_seen: '2026-10-05T10:15:00Z',
        series_count: 3,
        tag_key_count: 1,
    },
]

const meta: Meta<typeof MetricsSummaryTable> = {
    title: 'Scenes-App/Metrics/Summary table',
    component: MetricsSummaryTable,
    parameters: {
        layout: 'padded',
        mockDate: '2026-10-05T12:00:00Z',
        testOptions: { waitForSelector: '[data-attr="metrics-summary-metric-link"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/metrics/values/': { results: METRICS },
                '/api/projects/:team_id/metrics/names/': { results: [] },
                '/api/projects/:team_id/metrics/has_metrics/': { hasMetrics: true },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof MetricsSummaryTable>

export const Default: Story = {}
