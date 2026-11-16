import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { EventsTableApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ProjectEventsTableSetting } from './ProjectEventsTableSetting'

const meta: Meta = {
    title: 'Scenes-App/Settings/Events Table',
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj

const eventsTableMock = (eventsTable: EventsTableApi): ReturnType<typeof mswDecorator> =>
    mswDecorator({ get: { '/api/projects/:team_id/events_table/': eventsTable } })

export const OnTheOldTable: Story = {
    render: () => <ProjectEventsTableSetting />,
    decorators: [eventsTableMock({ use_new_events_table: null, reads_new_events_table: false, can_choose: true })],
}

export const MovedByPostHog: Story = {
    render: () => <ProjectEventsTableSetting />,
    decorators: [eventsTableMock({ use_new_events_table: null, reads_new_events_table: true, can_choose: true })],
}
