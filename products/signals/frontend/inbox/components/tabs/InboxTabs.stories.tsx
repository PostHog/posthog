import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { pullRequestReports, reportTabReports } from '../../__mocks__/inboxMocks'
import { SignalReport, SignalRun } from '../../types'
import { PullRequestsTab } from './PullRequestsTab'
import { ReportsTab } from './ReportsTab'
import { RunsTab } from './RunsTab'

// Stories for the inbox tab bodies. The flat report tabs (Reports / Pull requests) load via
// `reportListLogic`, so they get an mswDecorator that mocks the reports list endpoint; the
// Runs tab is prop-driven and receives mock runs directly. Use these to polish list density
// and the scout/signal run-card design.

const SAMPLE_RUNS: SignalRun[] = [
    {
        task_id: 'task-scout-1',
        kind: 'scout',
        title: 'signals-scout-error-tracking',
        status: 'in_progress',
        report_id: null,
        created_at: '2026-06-11T10:30:00Z',
    },
    {
        task_id: 'task-signal-1',
        kind: 'signal',
        title: 'Users hitting a crash when submitting the login form',
        status: 'completed',
        report_id: 'report-1',
        created_at: '2026-06-11T09:00:00Z',
    },
    {
        task_id: 'task-scout-2',
        kind: 'scout',
        title: 'signals-scout-surveys',
        status: 'failed',
        report_id: null,
        created_at: '2026-06-10T18:00:00Z',
    },
]

// Mocks the shared reports list endpoint so the logic-driven flat tabs render the given set.
function reportsListDecorator(reports: SignalReport[]): Decorator {
    return mswDecorator({
        get: {
            '/api/projects/:id/signals/reports': () => [
                200,
                { results: reports, count: reports.length, next: null, previous: null },
            ],
        },
    })
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/Tabs',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

export const Reports: Story = {
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab />
        </div>
    ),
}

export const ReportsEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab />
        </div>
    ),
}

export const PullRequests: Story = {
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab />
        </div>
    ),
}

export const PullRequestsEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab />
        </div>
    ),
}

export const Runs: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab runs={SAMPLE_RUNS} loading={false} />
        </div>
    ),
}

export const RunsLoading: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab runs={[]} loading />
        </div>
    ),
}

export const RunsEmpty: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab runs={[]} loading={false} />
        </div>
    ),
}
