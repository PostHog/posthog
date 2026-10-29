import type { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import { mswDecorator } from '~/mocks/browser'

import { mockRunLog, mockTask, mockTaskRun } from '../../__mocks__/inboxMocks'
import { FirstReportProgress } from './FirstReportProgress'

const meta: Meta<typeof FirstReportProgress> = {
    title: 'Scenes-App/Inbox/First report',
    component: FirstReportProgress,
    parameters: { mockDate: '2026-10-23T09:00:00Z' },
    render: (args): JSX.Element => (
        <div className="w-250">
            <FirstReportProgress {...args} />
        </div>
    ),
    args: {
        notificationEmail: 'person@example.com',
        result: {
            status: 'running',
            task_id: 'task-1',
            task_run_id: 'run-1',
            started_at: '2026-10-23T09:00:00Z',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/tasks/:taskId': [200, mockTask('task-1', 'completed')],
                '/api/projects/:id/tasks/:taskId/runs/:runId': [200, mockTaskRun('task-1', 'run-1')],
                '/api/projects/:id/tasks/:taskId/runs/:runId/log_entries': () => new HttpResponse(mockRunLog()),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const Running: Story = {}
export const RunningNarrow: Story = {
    render: (args): JSX.Element => (
        <div className="w-130">
            <FirstReportProgress {...args} />
        </div>
    ),
}
export const NoData: Story = { args: { result: { status: 'no_data' } } }
export const NoDataNarrow: Story = {
    ...NoData,
    render: (args): JSX.Element => (
        <div className="w-130">
            <FirstReportProgress {...args} />
        </div>
    ),
}
export const IncompleteWithoutRun: Story = { args: { result: { status: 'incomplete' } } }
