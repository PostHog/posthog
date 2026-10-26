import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EventsRetentionSettings } from './EventsRetentionSettings'

const meta: Meta<typeof EventsRetentionSettings> = {
    title: 'Scenes-App/Settings/Events Retention',
    component: EventsRetentionSettings,
    parameters: {
        mockDate: '2026-11-01',
    },
}
export default meta
type Story = StoryObj<typeof EventsRetentionSettings>

const retentionResponse = (retentionMonths: number, maxRetentionMonths: number): Record<string, unknown> => ({
    retention_months: retentionMonths,
    retained_from: '2024-11-01',
    max_retention_months: maxRetentionMonths,
    docs_url: 'https://posthog.com/docs/data/events-retention',
})

export const BoostPackage: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/events_retention/': retentionResponse(24, 36) },
        }),
    ],
}

export const LongestWindow: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/events_retention/': retentionResponse(84, 84) },
        }),
    ],
}
