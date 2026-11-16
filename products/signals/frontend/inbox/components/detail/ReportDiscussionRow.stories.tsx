import type { Meta, StoryObj } from '@storybook/react'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { mockTask } from '../../__mocks__/inboxMocks'
import type { ReportDiscussion } from '../../logics/inboxReportDetailLogic'
import { ReportDiscussionRow } from './ReportDiscussionRow'

const resolveAnswer = `Yes, you can resolve it. The fix shipped and the error rate went back to its earlier level.

The retry change is a follow-up, not a reason to keep the report open.`

function discussion(
    taskId: string,
    asker: string,
    question: string,
    summary: string | null,
    runStatus: TaskRunStatus,
    startedAt: string
): ReportDiscussion {
    const task = mockTask(taskId, runStatus)
    return {
        entry: {
            task: {
                ...task,
                created_by: { id: 1, uuid: `${taskId}-user`, distinct_id: taskId, first_name: asker, email: '' },
                latest_run: { ...task.latest_run, task_summary: summary },
            },
            purpose: 'other',
            purposeLabel: 'Signals: Discussion',
            startedAt,
        },
        question,
    }
}

const discussions = [
    discussion(
        'resolve-chat',
        'Ada',
        'Are we OK to resolve this report?',
        resolveAnswer,
        TaskRunStatus.COMPLETED,
        '2026-09-20T09:00:00Z'
    ),
    discussion(
        'deploy-chat',
        'Sam',
        'Which deploy introduced the error, and was it the same one that changed the invite form? The timing lines up with both.',
        'It started with the deploy that changed the invite serializer, not the form change.',
        TaskRunStatus.COMPLETED,
        '2026-09-20T10:30:00Z'
    ),
    discussion(
        'merge-chat',
        'Ada',
        'Is the fix safe to merge before the release?',
        null,
        TaskRunStatus.IN_PROGRESS,
        '2026-09-20T11:15:00Z'
    ),
]

function DiscussionList({ expandedTaskId }: { expandedTaskId: string | null }): JSX.Element {
    return (
        <div className="flex flex-col rounded border border-primary bg-surface-primary">
            {discussions.map((item) => (
                <ReportDiscussionRow
                    key={item.entry.task.id}
                    discussion={item}
                    expanded={item.entry.task.id === expandedTaskId}
                    onToggle={() => undefined}
                    onOpenChat={() => undefined}
                />
            ))}
        </div>
    )
}

const meta: Meta<typeof DiscussionList> = {
    title: 'Scenes-App/Inbox/Detail/Ask AI chats',
    component: DiscussionList,
    parameters: { layout: 'centered', viewMode: 'story', mockDate: '2026-09-20T12:00:00Z' },
    decorators: [
        (Story, context) => (
            // The report body column, and a phone, which is the narrowest place a report opens.
            <div
                className={`${context.parameters.bodyWidth === 'phone' ? 'w-[22rem]' : 'w-[40rem]'} max-w-[calc(100vw-2rem)] bg-primary p-4`}
            >
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof DiscussionList>

export const Collapsed: Story = {
    args: { expandedTaskId: null },
}

export const AnswerExpanded: Story = {
    args: { expandedTaskId: 'resolve-chat' },
}

export const PhoneWidth: Story = {
    parameters: { bodyWidth: 'phone' },
    args: { expandedTaskId: 'resolve-chat' },
}
