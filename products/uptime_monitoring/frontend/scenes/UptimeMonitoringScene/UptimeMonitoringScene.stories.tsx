import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { UptimeMonitorApi } from '../../generated/api.schemas'

function mockMonitor(
    overrides: Partial<UptimeMonitorApi> & Pick<UptimeMonitorApi, 'id' | 'name' | 'url'>
): UptimeMonitorApi {
    return {
        team_id: 1,
        method: 'GET',
        interval_seconds: 300,
        timeout_seconds: 10,
        enabled: true,
        created_at: '2026-10-20T10:00:00Z',
        updated_at: '2026-10-20T10:00:00Z',
        ...overrides,
    }
}

const MOCK_MONITORS: UptimeMonitorApi[] = [
    mockMonitor({ id: '01900000-0000-7000-8000-000000000001', name: 'Marketing site', url: 'https://example.com' }),
    mockMonitor({
        id: '01900000-0000-7000-8000-000000000002',
        name: 'Public API health',
        url: 'https://api.example.com/health',
        interval_seconds: 60,
    }),
    mockMonitor({
        id: '01900000-0000-7000-8000-000000000003',
        name: 'Status page',
        url: 'https://status.example.com',
        interval_seconds: 3600,
        enabled: false,
    }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Uptime monitoring',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-22',
        pageUrl: urls.uptimeMonitoring(),
        featureFlags: [FEATURE_FLAGS.UPTIME_MONITORING],
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/uptime_monitors/': toPaginatedResponse(MOCK_MONITORS) },
        }),
    ],
}
export default meta
type Story = StoryObj<{}>

export const MonitorList: Story = {}
