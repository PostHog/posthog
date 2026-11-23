import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { useStorybookMocks } from '~/mocks/browser'

import type { SlackScoutChannelSourceApi } from 'products/signals/frontend/generated/api.schemas'

import { SlackChannelScoutsCard } from './SlackChannelScoutsCard'

const SOURCE: SlackScoutChannelSourceApi = {
    id: '0190f1d2-0000-7000-8000-000000000001',
    channels: [
        { id: 'C01', name: 'bug-reports', table_name: 'slack.c01' },
        { id: 'C02', name: 'feedback', table_name: 'slack.c02' },
        { id: 'C03', name: 'new-channel', table_name: null },
    ],
}

function Card({
    sources,
    scoutNames = [],
}: {
    sources: SlackScoutChannelSourceApi[]
    scoutNames?: string[]
}): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/slack_channel_scouts/channels/': { sources },
            '/api/projects/:team_id/signals/scout/configs/': scoutNames.map((name, index) => ({
                id: `scout-${index}`,
                skill_name: `slack-scout-${index}`,
                display_name: name,
            })),
        },
    })
    return (
        <div className="max-w-4xl p-4">
            <SlackChannelScoutsCard />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/Slack channel scouts card',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // Single-consumer card behind a flag: render and run play functions, but keep no snapshot baseline.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj

export const NotConnected: Story = {
    render: () => <Card sources={[]} />,
}

export const WithScouts: Story = {
    render: () => <Card sources={[SOURCE]} scoutNames={['Support channels', 'Feedback digest']} />,
}

export const CreateForm: Story = {
    render: () => <Card sources={[SOURCE]} />,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: 'New Slack scout' }))
    },
}
