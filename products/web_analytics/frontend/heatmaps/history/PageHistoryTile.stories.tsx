import type { Meta, StoryObj } from '@storybook/react'

import type { HeatmapScreenshotHistoryItemApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { PageHistoryTile } from './PageHistoryTile'

const capture: HeatmapScreenshotHistoryItemApi = {
    id: '00000000-0000-4000-8000-000000000001',
    captured_on: '2024-01-21',
    captured_at: '2024-01-21T02:40:00Z',
    width: 1024,
    timezone: 'UTC',
    day_start: '2024-01-21T00:00:00Z',
    day_end: '2024-01-22T00:00:00Z',
    expires_at: '2024-04-20T00:00:00Z',
    revision: '00000000-0000-4000-8000-000000000002',
    latest_request: null,
    thumbnail_url:
        'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="240"%3E%3Crect width="320" height="240" fill="%23e3e6dd"/%3E%3Crect x="24" y="24" width="272" height="60" fill="white"/%3E%3Crect x="24" y="100" width="80" height="80" fill="white"/%3E%3Crect x="120" y="100" width="80" height="80" fill="white"/%3E%3Crect x="216" y="100" width="80" height="80" fill="white"/%3E%3C/svg%3E',
    content_url: '/example-capture.jpg',
    trigger: 'scheduled',
    status: 'ok',
    failure_cause: null,
    page_status: 200,
}

const meta: Meta<typeof PageHistoryTile> = {
    title: 'Products/Web Analytics/Heatmaps/Page history tile',
    component: PageHistoryTile,
    parameters: { mockDate: '2024-01-21T12:00:00Z' },
    args: { capture, selected: false, onSelect: () => {} },
    decorators: [
        (Story) => (
            <div className="w-28">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof PageHistoryTile>

export const Captured: Story = {}
export const SelectedBackground: Story = { args: { selected: true } }
export const MissingThumbnail: Story = { args: { capture: { ...capture, thumbnail_url: null } } }
export const FailedReplacement: Story = {
    args: {
        capture: {
            ...capture,
            latest_request: {
                request_id: '00000000-0000-4000-8000-000000000003',
                state: 'failed',
                deadline: '2024-01-21T12:30:00Z',
                completed_at: '2024-01-21T12:02:00Z',
                failure_cause: 'browserless_timeout',
                page_status: null,
            },
        },
    },
}
export const FirstCaptureInProgress: Story = {
    args: {
        capture: {
            ...capture,
            status: 'pending',
            revision: null,
            content_url: null,
            thumbnail_url: null,
            captured_at: null,
            latest_request: {
                request_id: '00000000-0000-4000-8000-000000000003',
                state: 'running',
                deadline: '2024-01-21T12:30:00Z',
                completed_at: null,
                failure_cause: null,
                page_status: null,
            },
        },
    },
}
