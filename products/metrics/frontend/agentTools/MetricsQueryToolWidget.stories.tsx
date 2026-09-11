import type { Meta, StoryObj } from '@storybook/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

import { MetricsQueryToolWidget } from './MetricsQueryToolWidget'

const meta: Meta<typeof MetricsQueryToolWidget> = {
    title: 'Scenes-App/Max AI/Metrics query tool',
    component: MetricsQueryToolWidget,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof MetricsQueryToolWidget>

function points(values: number[]): Record<string, unknown>[] {
    return values.map((value, index) => ({
        time: `2026-09-08T10:${String(index).padStart(2, '0')}:00Z`,
        value,
    }))
}

function message(results: Record<string, unknown>[]): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'query-metrics',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: {},
        innerInput: {
            query: {
                metricName: 'http_server_request_duration_seconds',
                aggregation: 'p95',
                groupBy: [{ key: 'service_name' }],
                dateFrom: '2026-09-08T10:00:00Z',
            },
        },
        rawOutput: { results },
        content: [],
        status: 'completed',
    }
}

const SERIES: Record<string, unknown>[] = [
    {
        metric_name: 'http_server_request_duration_seconds',
        labels: { service_name: 'api-gateway' },
        points: points([0.21, 0.24, 0.22, 0.63, 1.42, 1.51]),
    },
    {
        metric_name: 'http_server_request_duration_seconds',
        labels: { service_name: 'checkout' },
        points: points([0.11, 0.12, 0.11, 0.13, 0.12, 0.14]),
    },
    {
        metric_name: 'http_server_request_duration_seconds',
        labels: { service_name: 'search' },
        points: [...points([0.32, 0.31, 0.33, 0.3]), { time: '2026-09-08T10:04:00Z', value: null }],
    },
]

export const WithSeries: Story = {
    render: () => (
        <MetricsQueryToolWidget message={message(SERIES)} isLastInGroup displayName="Query metrics" turnComplete />
    ),
    name: 'Completed with series',
}

export const NoMatches: Story = {
    render: () => (
        <MetricsQueryToolWidget message={message([])} isLastInGroup displayName="Query metrics" turnComplete />
    ),
    name: 'No matching series',
}
