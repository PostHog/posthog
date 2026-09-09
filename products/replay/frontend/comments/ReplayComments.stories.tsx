import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ReplayTabs } from '~/types'

const comment = (id: string, secondsIntoRecording: number, content: string): Record<string, any> => ({
    id,
    content,
    rich_content: null,
    version: 0,
    created_at: '2023-01-31T16:20:00Z',
    created_by: null,
    scope: 'Replay',
    item_id: `recording-${id}`,
    item_context: {
        time_in_recording: '2023-01-31T16:00:00Z',
        milliseconds_into_recording: secondsIntoRecording * 1000,
    },
    is_task: false,
    completed_at: null,
    completed_by: null,
    slack_thread: null,
})

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Comments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(ReplayTabs.Comments),
    },
}
export default meta

type Story = StoryObj<{}>

export const ReplayComments: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/comments/': {
                    next: null,
                    previous: null,
                    results: [
                        comment('1', 72, 'The checkout button does nothing on the first click.'),
                        comment('2', 605, 'This user could not find the export option.'),
                    ],
                },
            },
        }),
    ],
}

export const ReplayCommentsEmpty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/comments/': { next: null, previous: null, results: [] },
            },
        }),
    ],
}
