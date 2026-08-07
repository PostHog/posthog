import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockSourceConfigs, pullRequestReports, reportTabReports } from '../../__mocks__/inboxMocks'
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

// A wizard run the session detector reads as live: recent enough not to be aged out, and not stale.
const SELF_DRIVING_SESSION_IN_FLIGHT = {
    id: 'wizard-session-1',
    workflow_id: 'self-driving',
    run_phase: 'running',
    started_at: '2026-06-10T23:50:00Z',
    updated_at: '2026-06-10T23:59:00Z',
    is_stale: false,
    created_by: null,
}

/**
 * Reports tab with nothing in it, set up so the empty-state hint can explain why: whether a setup
 * run is in flight, and failing that, how much is watching the project and when it last swept.
 * `PRODUCT_AUTONOMY` is what makes the sources logic load at all, so without it the hint would only
 * ever be able to count scouts.
 */
function emptyStateStory({ runInFlight, lastRunAt }: { runInFlight: boolean; lastRunAt: string | null }): Story {
    return {
        parameters: { featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY] },
        decorators: [
            mswDecorator({
                get: {
                    '/api/projects/:id/signals/reports': () => [
                        200,
                        { results: [], count: 0, next: null, previous: null },
                    ],
                    '/api/projects/:id/wizard/sessions/latest': () => [
                        200,
                        runInFlight ? SELF_DRIVING_SESSION_IN_FLIGHT : null,
                    ],
                    '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                    '/api/projects/:id/signals/scout/configs': () => [
                        200,
                        [
                            {
                                id: 'scout-1',
                                skill_name: 'signals-scout-error-tracking',
                                enabled: true,
                                last_run_at: lastRunAt,
                            },
                            { id: 'scout-2', skill_name: 'signals-scout-surveys', enabled: true, last_run_at: null },
                        ],
                    ],
                    '/api/projects/:id/signals/scout/runs': () => [200, []],
                },
            }),
        ],
        render: () => (
            <div className="bg-primary min-h-screen">
                <ReportsTab />
            </div>
        ),
    }
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

// Setup is still running, so the empty inbox is expected rather than broken.
export const ReportsEmptyDuringSetup: Story = emptyStateStory({ runInFlight: true, lastRunAt: null })

export const ReportsEmptyAfterSetup: Story = emptyStateStory({ runInFlight: false, lastRunAt: '2026-06-10T21:00:00Z' })

// Set up, but no scout has swept yet — the first findings are still hours out.
export const ReportsEmptyNeverSwept: Story = emptyStateStory({ runInFlight: false, lastRunAt: null })

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
