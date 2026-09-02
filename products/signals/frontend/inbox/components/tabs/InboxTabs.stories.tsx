import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { pullRequestReports, reportTabReports } from '../../__mocks__/inboxMocks'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { SignalReport, SignalRun } from '../../types'
import { PullRequestsTab } from './PullRequestsTab'
import { ReportsTab } from './ReportsTab'
import { ReportsTabLegacy } from './ReportsTabLegacy'
import { RunsTab } from './RunsTab'

// Stories for the inbox tab bodies. The Reports tab loads each report state via `reportListLogic`,
// so it gets an mswDecorator that mocks the reports list endpoint; the Runs panel is prop-driven
// and receives mock runs directly. Use these to polish list density and the run-card design.

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

// One mocked endpoint feeds every report state, so the same rows come back for each state's
// request and the flat list deduplicates them — enough to judge the list rhythm, which is what
// these stories are for.
function ReportsTabStory({ searchParams }: { searchParams?: Record<string, string> }): JSX.Element {
    useMountedLogic(inboxSceneLogic)
    useEffect(() => {
        router.actions.push(urls.inbox('reports'), searchParams ?? {})
    }, [searchParams])
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
        featureFlags: { [FEATURE_FLAGS.INBOX_REDESIGN]: true },
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

// The default view: one flat list over the default-selected open-work states.
export const Reports: Story = {
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => <ReportsTabStory />,
}

// The state filter narrowing the list to one state via the shared `state` URL param.
export const ReportsStateFiltered: Story = {
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => <ReportsTabStory searchParams={{ state: 'monitoring' }} />,
}

// Nothing anywhere: the whole-list empty state.
export const ReportsEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => <ReportsTabStory />,
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

// The flat tabs with the redesign flag off: one list per tab under the search and filter bar.
export const ReportsLegacy: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.INBOX_REDESIGN]: false } },
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTabLegacy />
        </div>
    ),
}

export const PullRequestsLegacy: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.INBOX_REDESIGN]: false } },
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab />
        </div>
    ),
}
