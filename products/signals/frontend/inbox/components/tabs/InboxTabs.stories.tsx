import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { pullRequestReports, reportTabReports } from '../../__mocks__/inboxMocks'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { DEFAULT_OPEN_SECTIONS, inboxReportSectionsLogic } from '../../logics/inboxReportSectionsLogic'
import { INBOX_REPORT_SECTION_KEYS, SignalReport, SignalRun } from '../../types'
import { ReportsTab } from './ReportsTab'
import { RunsTab } from './RunsTab'

// Stories for the inbox tab bodies. The Reports tab loads each section via `reportListLogic`, so it
// gets an mswDecorator that mocks the reports list endpoint; the Runs panel is prop-driven and
// receives mock runs directly. Use these to polish section density and the run-card design.

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

// One mocked endpoint feeds every section, so each renders the same rows — enough to judge the
// section rhythm, which is what these stories are for.
function ReportsTabStory({ expandAll = false }: { expandAll?: boolean }): JSX.Element {
    useMountedLogic(inboxSceneLogic)
    const sectionsLogic = useMountedLogic(inboxReportSectionsLogic)
    useEffect(() => {
        router.actions.push(urls.inbox('reports'))
        if (expandAll) {
            INBOX_REPORT_SECTION_KEYS.filter((key) => !DEFAULT_OPEN_SECTIONS[key]).forEach((key) =>
                sectionsLogic.actions.toggleSection(key)
            )
        }
    }, [expandAll, sectionsLogic])
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

// The default arrangement: Needs a decision and Monitoring open, Resolved collapsed.
export const Reports: Story = {
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => <ReportsTabStory />,
}

// Every section open, including the ones that start collapsed.
export const ReportsAllSectionsExpanded: Story = {
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => <ReportsTabStory expandAll />,
}

// Nothing anywhere: the whole-list empty state rather than a per-section one.
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
