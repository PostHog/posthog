import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
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

// The scene replaces every tab with the session replay product empty state until its setup probe
// finds a recording, so the recordings list has to answer before any of this tab is on screen.
const sceneMocks = (comments: Record<string, any>[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings': { has_next: false, results: recordings },
            '/api/projects/:team_id/comments/': { next: null, previous: null, results: comments },
        },
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
        sceneMocks([
            comment('1', 72, 'The checkout button does nothing on the first click.'),
            comment('2', 605, 'This user could not find the export option.'),
        ]),
    ],
}

export const ReplayCommentsEmpty: Story = {
    decorators: [sceneMocks([])],
}
