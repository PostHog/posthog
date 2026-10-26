import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EventsRetentionSettings } from './EventsRetentionSettings'

const meta: Meta<typeof EventsRetentionSettings> = {
    title: 'Scenes-App/Settings/Organization/Events Retention',
    component: EventsRetentionSettings,
    parameters: {
        mockDate: '2026-11-01',
    },
}
export default meta
type Story = StoryObj<typeof EventsRetentionSettings>

const retentionMocks = (chosenMonths: number | null, maxRetentionMonths: number): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/events_retention/': {
                retention_months: chosenMonths ?? maxRetentionMonths,
                retained_from: '2024-11-01',
                docs_url: 'https://posthog.com/docs/data/events-retention',
            },
            '/api/organizations/:organization_id/events_retention_setting/': {
                retention_months: chosenMonths,
                max_retention_months: maxRetentionMonths,
            },
        },
    })

export const BoostPackage: Story = {
    decorators: [retentionMocks(24, 36)],
}

export const LongestWindow: Story = {
    decorators: [retentionMocks(null, 84)],
}
