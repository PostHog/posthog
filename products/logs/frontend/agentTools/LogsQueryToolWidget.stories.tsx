import type { Meta, StoryObj } from '@storybook/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

import { LogsQueryToolWidget } from './LogsQueryToolWidget'

const meta: Meta<typeof LogsQueryToolWidget> = {
    title: 'Scenes-App/Max AI/Logs query tool',
    component: LogsQueryToolWidget,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof LogsQueryToolWidget>

function message(results: Record<string, unknown>[]): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'query-logs',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: {},
        innerInput: {
            query: {
                serviceNames: ['api-gateway'],
                severityLevels: ['warn', 'error'],
                dateRange: { date_from: '-1h' },
            },
        },
        rawOutput: { results },
        content: [],
        status: 'completed',
    }
}

const ROWS: Record<string, unknown>[] = [
    { severity_text: 'error', body: 'upstream connect timeout after 5000ms', timestamp: '2026-09-08T10:00:03Z' },
    { severity_text: 'warn', body: 'retry 2/3 for GET /v1/orders', timestamp: '2026-09-08T10:00:02Z' },
    { severity_text: 'error', body: 'circuit breaker open for checkout', timestamp: '2026-09-08T10:00:01Z' },
    { severity_text: 'info', body: 'request served in 12ms', timestamp: '2026-09-08T10:00:00Z' },
]

export const WithRows: Story = {
    render: () => <LogsQueryToolWidget message={message(ROWS)} isLastInGroup displayName="Query logs" turnComplete />,
    name: 'Completed with rows',
}

export const NoMatches: Story = {
    render: () => <LogsQueryToolWidget message={message([])} isLastInGroup displayName="Query logs" turnComplete />,
    name: 'No matching logs',
}
