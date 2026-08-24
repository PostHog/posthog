import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { pullRequestReports, reportTabReports } from '../../__mocks__/inboxMocks'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { InboxFlatListTabKey, SignalReport, SignalRun } from '../../types'
import { ReportsTab } from './ReportsTab'
import { RunsTab } from './RunsTab'

// Stories for the inbox tab bodies. The Reports tab loads its views via `reportListLogic`, so it
// gets an mswDecorator that mocks the reports list endpoint; the Runs panel is prop-driven and
// receives mock runs directly. Use these to polish list density and the run-card design.

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

// Mocks the shared reports list endpoint so the logic-driven views render the given set.
function reportsListDecorator(reports: SignalReport[]): Decorator {
    return mswDecorator({
        get: {
            '/api/projects/:id/signals/reports': () => [
                200,
                { results: reports, count: reports.length, next: null, previous: null },
            ],
            '/api/projects/:id/signals/reports/available_reviewers': () => [200, []],
            '/api/projects/:id/signals/scout/configs': () => [200, []],
        },
    })
}

// The Reports tab reads its active view from the scene logic, which reads it from the URL.
function ReportsTabAt({ view }: { view: InboxFlatListTabKey }): JSX.Element {
    useMountedLogic(inboxSceneLogic)
    useEffect(() => {
        router.actions.push(urls.inbox('reports'), view === 'needs-decision' ? {} : { view })
    }, [view])
    return (
        <div className="bg-primary min-h-screen">
            <ReportsTab />
        </div>
    )
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

export const NeedsDecision: Story = {
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => <ReportsTabAt view="needs-decision" />,
}

export const NeedsDecisionEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => <ReportsTabAt view="needs-decision" />,
}

export const Monitoring: Story = {
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => <ReportsTabAt view="monitoring" />,
}

export const MonitoringEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => <ReportsTabAt view="monitoring" />,
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
