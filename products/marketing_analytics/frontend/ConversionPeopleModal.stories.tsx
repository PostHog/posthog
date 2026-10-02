import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { ConversionPeopleModal } from './ConversionPeopleModal'
import { ConversionPeopleResponseApi } from './generated/api.schemas'

const meta: Meta<typeof ConversionPeopleModal> = {
    title: 'Marketing Analytics/Conversion people',
    component: ConversionPeopleModal,
    args: {
        goalName: 'Purchases',
        request: {
            source: { kind: 'MarketingAnalyticsTableQuery', properties: [], dateRange: { date_from: '-7d' } },
            goal_id: 'purchase',
            group: 'winter-sale',
            source_name: 'google',
        },
        onClose: () => {},
    },
    parameters: { testOptions: { waitForSelector: '.LemonModal', snapshotTargetSelector: '.LemonModal' } },
}
export default meta
type Story = StoryObj<typeof meta>

const people: ConversionPeopleResponseApi = {
    results: ['alex', 'sam', 'taylor', 'robin'].map((name, index) => ({
        id: `00000000-0000-4000-8000-00000000000${index + 1}`,
        name: `${name}@example.com`,
    })),
    has_more: false,
    preparing: false,
}

export const WithPeople: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_people/': async ({ request }) => {
                    const { search = '' } = (await request.json()) as { search?: string }
                    return { ...people, results: people.results.filter((person) => person.name.includes(search)) }
                },
            },
        })
        return <ConversionPeopleModal {...args} />
    },
    parameters: { testOptions: { waitForSelector: 'a[href*="persons/00000000"]' } },
}

export const Preparing: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_people/': {
                    ...people,
                    results: [],
                    preparing: true,
                },
            },
        })
        return <ConversionPeopleModal {...args} />
    },
}

export const Empty: Story = {
    render: (args) => {
        useStorybookMocks({
            post: { '/api/projects/:team_id/marketing_analytics/conversion_people/': { ...people, results: [] } },
        })
        return <ConversionPeopleModal {...args} />
    },
}

export const Error: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_people/': [
                    500,
                    { detail: 'Could not load people.' },
                ],
            },
        })
        return <ConversionPeopleModal {...args} />
    },
}
