import type { Meta, StoryObj } from '@storybook/react'

import { makeReport } from '../../__mocks__/inboxMocks'
import { SignalReportAssignmentLabel } from './SignalReportAssignmentLabel'

const meta: Meta<typeof SignalReportAssignmentLabel> = {
    title: 'Scenes-App/Inbox/Badges/SignalReportAssignmentLabel',
    component: SignalReportAssignmentLabel,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof SignalReportAssignmentLabel>

export const ExternalAgentClaim: Story = {
    args: {
        report: makeReport({
            assignee: {
                kind: 'agent',
                user: {
                    id: 1,
                    uuid: 'user-1',
                    first_name: 'Mikayla',
                    last_name: 'Thompson',
                    email: 'mikayla@example.com',
                },
                task_id: null,
                agent: 'Codex',
                claimed_at: '2026-09-04T12:00:00Z',
            },
            work_state: 'working',
        }),
    },
}

export const PostHogPullRequest: Story = {
    args: {
        report: makeReport({
            implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12001',
            implementation_pr_state: 'open',
            work_state: 'in_review',
            assignee: {
                kind: 'task',
                user: null,
                task_id: '019e64b8-0000-7000-8000-000000000001',
                agent: null,
                claimed_at: '2026-09-04T12:00:00Z',
            },
        }),
    },
}

export const ExternalPullRequest: Story = {
    args: {
        report: makeReport({
            implementation_pr_url: 'https://github.com/example/project/pull/42',
            implementation_pr_state: 'open',
            work_state: 'in_review',
            assignee: {
                kind: 'agent',
                user: {
                    id: 1,
                    uuid: 'user-1',
                    first_name: 'Mikayla',
                    last_name: 'Thompson',
                    email: 'mikayla@example.com',
                },
                task_id: null,
                agent: 'Codex',
                claimed_at: '2026-09-04T12:00:00Z',
            },
        }),
    },
}
