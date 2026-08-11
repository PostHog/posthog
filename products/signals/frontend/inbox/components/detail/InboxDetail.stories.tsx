import type { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import { mswDecorator } from '~/mocks/browser'

import {
    makeReport,
    mockArtefacts,
    mockBranchDiff,
    mockReviewers,
    mockRunLog,
    mockSignals,
    mockTask,
    mockTaskRun,
    pullRequestReports,
    reportTabReports,
    runReportsMany,
} from '../../__mocks__/inboxMocks'
import { SignalReportStatus } from '../../types'
import { AgentRunDetail } from './AgentRunDetail'
import { PullRequestDetail } from './PullRequestDetail'
import { ReportDetail } from './ReportDetail'

const mixedPrChecks = {
    checks: [
        {
            name: 'Frontend CI / TypeScript check',
            status: 'completed',
            conclusion: 'failure',
            url: 'https://github.com/PostHog/posthog/actions/runs/12001/jobs/1',
        },
        {
            name: 'Backend CI / Django tests: Core (persons-on-events off), Python 3.13, ClickHouse 26.3',
            status: 'in_progress',
            conclusion: null,
            url: 'https://github.com/PostHog/posthog/actions/runs/12001/jobs/2',
        },
        {
            name: 'Product analytics / Jest',
            status: 'completed',
            conclusion: 'success',
            url: 'https://github.com/PostHog/posthog/actions/runs/12001/jobs/3',
        },
        {
            name: 'Visual regression',
            status: 'completed',
            conclusion: 'cancelled',
            url: 'https://github.com/PostHog/posthog/actions/runs/12001/jobs/4',
        },
        {
            name: 'Dependency review',
            status: 'completed',
            conclusion: 'stale',
            url: 'https://github.com/PostHog/posthog/actions/runs/12001/jobs/5',
        },
        {
            name: 'Codecov / project',
            status: 'completed',
            conclusion: 'neutral',
            url: 'https://app.codecov.io/gh/PostHog/posthog',
        },
    ],
}

const successfulPrChecks = {
    checks: [
        'CI preflight',
        'Frontend CI / TypeScript check',
        'Frontend CI / Jest',
        'Backend CI / Django tests',
        'Visual regression',
    ].map((name, index) => ({
        name,
        status: 'completed',
        conclusion: 'success',
        url: `https://github.com/PostHog/posthog/actions/runs/12002/jobs/${index + 1}`,
    })),
}

// Detail-body stories. Each detail component mounts the keyed `inboxReportDetailLogic`,
// which fetches artefacts / signals / tasks – mocked here. Polish the two-column detail
// layout (summary, evidence, runs, reviewers) against the desktop detail views.

const detailMocks = mswDecorator({
    get: {
        '/api/projects/:id/signals/reports/:reportId/artefacts': (req) => [
            200,
            mockArtefacts(req.params.reportId as string),
        ],
        '/api/projects/:id/signals/reports/:reportId/artefacts/:artefactId/diff/': () => [200, mockBranchDiff()],
        '/api/projects/:id/signals/reports/:reportId/signals': (req) => [
            200,
            { report: null, signals: mockSignals(req.params.reportId as string, 4) },
        ],
        '/api/projects/:id/signals/reports/:reportId/pr_checks/': (req) => [
            200,
            req.params.reportId === pullRequestReports[1].id ? successfulPrChecks : mixedPrChecks,
        ],
        '/api/projects/:id/signals/reports/:reportId/pr_comments/': () => [200, { comments: [] }],
        '/api/projects/:id/signals/reports/available_reviewers': () => [200, mockReviewers],
        // Terminal run status so the inline run viewer replays its static log instead of opening SSE.
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string, 'completed')],
        '/api/projects/:id/tasks/:taskId/runs/:runId': (req) => [
            200,
            mockTaskRun(req.params.taskId as string, req.params.runId as string),
        ],
        '/api/projects/:id/tasks/:taskId/runs/:runId/logs': () => new HttpResponse(mockRunLog()),
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Detail',
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2026-06-11' },
    decorators: [detailMocks],
}
export default meta

type Story = StoryObj

function Frame({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="bg-primary min-h-screen py-4">{children}</div>
}

export const Report: Story = {
    render: () => (
        <Frame>
            <ReportDetail report={reportTabReports[0]} tab="reports" />
        </Frame>
    ),
}

export const ReportMinimal: Story = {
    render: () => (
        <Frame>
            <ReportDetail
                report={makeReport({
                    title: 'No summary yet',
                    summary: null,
                    status: SignalReportStatus.CANDIDATE,
                    signal_count: 1,
                })}
                tab="reports"
            />
        </Frame>
    ),
}

export const PullRequest: Story = {
    render: () => (
        <Frame>
            <PullRequestDetail report={pullRequestReports[0]} />
        </Frame>
    ),
}

export const PullRequestChecksPassing: Story = {
    render: () => (
        <Frame>
            <PullRequestDetail report={pullRequestReports[1]} />
        </Frame>
    ),
}

export const RunInProgress: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={runReportsMany.find((r) => r.status === SignalReportStatus.IN_PROGRESS)!} />
        </Frame>
    ),
}

export const RunFailed: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={runReportsMany.find((r) => r.status === SignalReportStatus.FAILED)!} />
        </Frame>
    ),
}

export const RunReady: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={pullRequestReports[0]} />
        </Frame>
    ),
}

// Inline review threads anchored onto the branch diff from `mockBranchDiff()`, with the viewer's own
// GitHub identity connected so the composer, the edit/delete affordances and the reaction pills all
// render. The default `detailMocks` return no comments and no personal connection, which is the
// empty state the other PR stories cover.
const reviewComment = (
    overrides: Partial<Record<string, unknown>> & { id: string; body: string }
): Record<string, unknown> => ({
    author: 'octocat',
    author_avatar_url: null,
    created_at: '2026-06-11T09:00:00Z',
    url: `https://github.com/PostHog/posthog/pull/12001#discussion_r${overrides.id}`,
    comment_type: 'review',
    path: 'frontend/src/scenes/invites/inviteLogic.ts',
    line: 45,
    start_line: null,
    side: 'RIGHT',
    diff_hunk: null,
    in_reply_to_id: null,
    commit_id: 'abc123',
    reactions: [],
    ...overrides,
})

const inlineReviewComments = [
    reviewComment({
        id: '1',
        author: 'twixes',
        body: 'Should this bail out before the toast fires? Right now an empty list still hits the loading state for a frame.',
        reactions: [{ id: '11', content: '+1', user_login: 'octocat' }],
    }),
    reviewComment({
        id: '2',
        author: 'octocat',
        body: 'Good catch, the early return covers it. Moved the guard above the toast.',
        in_reply_to_id: '1',
        created_at: '2026-06-11T09:12:00Z',
    }),
    reviewComment({
        id: '3',
        author: 'twixes',
        body: 'Worth trimming here too, so a whitespace-only name does not count as a recipient.',
        path: 'frontend/src/scenes/invites/InviteRow.tsx',
        line: 12,
        created_at: '2026-06-11T09:20:00Z',
        reactions: [
            { id: '31', content: 'heart', user_login: 'octocat' },
            { id: '32', content: 'rocket', user_login: 'twixes' },
        ],
    }),
]

const inlineReviewMocks = mswDecorator({
    get: {
        '/api/projects/:id/signals/reports/:reportId/pr_comments/': () => [200, { comments: inlineReviewComments }],
        '/api/users/@me/integrations/': () => [
            200,
            {
                results: [
                    {
                        id: 1,
                        installation_id: '12345',
                        repository_selection: 'all',
                        account: { type: 'Organization', name: 'PostHog' },
                        github_login: 'twixes',
                        uses_shared_installation: true,
                        created_at: '2026-05-01T00:00:00Z',
                    },
                ],
            },
        ],
    },
})

export const PullRequestInlineReview: Story = {
    decorators: [inlineReviewMocks],
    render: () => (
        <Frame>
            <PullRequestDetail report={pullRequestReports[0]} />
        </Frame>
    ),
}
