import type { Meta, StoryObj } from '@storybook/react'

import { IconTerminal } from '@posthog/icons'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { mockTask } from '../../__mocks__/inboxMocks'
import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { DetailSection } from './DetailSection'
import { ReportTaskRow } from './ReportTaskRow'

// What an agent writes about itself: goal, outcome, where the work landed, how far it verified.
const implementationSummary = `Made the invite endpoint reject a blank recipient before it reaches the mailer.

The 500 came from the mailer raising on an empty address, so the serializer now validates it and the
view answers 400 instead.

Branch: inbox/fix-invites — PR #12001. Ran the invites API tests locally; they pass.`

function entry(
    taskId: string,
    purposeLabel: string,
    summary: string | null,
    runStatus?: TaskRunStatus
): ReportTaskEntry {
    const task = mockTask(taskId, runStatus)
    return {
        task: { ...task, latest_run: { ...task.latest_run, task_summary: summary } },
        purpose: purposeLabel === 'Implementation' ? 'implementation' : 'research',
        purposeLabel,
        startedAt: '2026-09-20T09:00:00Z',
    }
}

function RunsSection({ entries }: { entries: ReportTaskEntry[] }): JSX.Element {
    return (
        <DetailSection icon={<IconTerminal />} title="Runs" collapsible>
            <div className="flex flex-col gap-0.5">
                {entries.map((taskEntry) => (
                    <ReportTaskRow
                        key={taskEntry.task.id}
                        entry={taskEntry}
                        expanded={false}
                        onToggle={() => undefined}
                    />
                ))}
            </div>
        </DetailSection>
    )
}

const meta: Meta<typeof RunsSection> = {
    title: 'Scenes-App/Inbox/Detail/Runs',
    component: RunsSection,
    parameters: { layout: 'centered', viewMode: 'story' },
    decorators: [
        (Story, context) => (
            // The rail is 26rem wide, and about 20rem of it survives next to an open side panel.
            <div
                className={`${context.parameters.railWidth === 'narrow' ? 'w-[20rem]' : 'w-[26rem]'} max-w-[calc(100vw-2rem)] rounded border bg-primary p-4`}
            >
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof RunsSection>

export const WithAndWithoutSummaries: Story = {
    args: {
        entries: [
            entry('impl-task', 'Implementation', implementationSummary, TaskRunStatus.COMPLETED),
            entry('research-task', 'Research', null),
        ],
    },
}

export const NarrowRail: Story = {
    parameters: { railWidth: 'narrow' },
    args: {
        entries: [
            entry('impl-task', 'Implementation', implementationSummary, TaskRunStatus.COMPLETED),
            entry('research-task', 'Research', null),
        ],
    },
}
