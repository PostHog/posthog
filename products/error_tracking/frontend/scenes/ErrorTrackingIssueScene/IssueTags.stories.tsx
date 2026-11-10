import type { Meta, StoryObj } from '@storybook/react'

import { IssueTags } from './IssueTags'

const meta: Meta<typeof IssueTags> = {
    title: 'Scenes-App/ErrorTracking/IssueTags',
    component: IssueTags,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof IssueTags>

export const AnsweredByAIAndManually: Story = {
    args: {
        tags: [
            {
                key: 'cause_in_trace',
                label: 'Cause in stack trace',
                description: 'The stack trace shows the line that caused the error.',
                value: true,
                source: 'jev',
            },
            {
                key: 'user_facing',
                label: 'Seen by users',
                description: 'People using the app saw this error.',
                value: true,
                source: 'manual',
            },
        ],
    },
}
