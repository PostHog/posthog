import { Meta, StoryObj } from '@storybook/react'

import type { HealthIssue } from 'scenes/health/types'

import { mswDecorator } from '~/mocks/browser'

import { StoppedEventsNotice } from './StoppedEventsNotice'

const issue = (id: string, payload: Record<string, any>): HealthIssue => ({
    id,
    kind: 'event_stopped',
    severity: 'warning',
    status: 'active',
    dismissed: false,
    snoozed_until: null,
    payload,
    created_at: '2026-11-08T03:40:00Z',
    updated_at: '2026-11-08T03:40:00Z',
    resolved_at: null,
})

const issuesMock = (results: HealthIssue[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/health_issues/': { results, count: results.length },
        },
    })

const meta: Meta<typeof StoppedEventsNotice> = {
    component: StoppedEventsNotice,
    title: 'Scenes-App/Product analytics home stopped events',
    parameters: {
        mockDate: '2026-11-10',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="stopped-event"]' },
    },
}
export default meta

type Story = StoryObj<typeof StoppedEventsNotice>

export const SeveralEvents: Story = {
    decorators: [
        issuesMock([
            issue('1', {
                event: 'checkout_completed',
                event_definition_id: 'def-1',
                last_seen_at: '2026-11-05T09:00:00Z',
                insight_count: 4,
                annotation: { content: 'Released checkout v2', marked_at: '2026-11-05T08:00:00Z' },
            }),
            issue('2', {
                event: 'invite_sent',
                event_definition_id: 'def-2',
                last_seen_at: '2026-11-03T15:00:00Z',
                insight_count: 1,
            }),
        ]),
    ],
}
