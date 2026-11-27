import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { PRBrowserPageApi } from 'products/signals/frontend/generated/api.schemas'

import {
    MONITORING_MOCK_NOW,
    monitoringChecksForReport,
    monitoringMetricQueryHandler,
    monitoringRows,
} from '../../__mocks__/monitoringMocks'
import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { MonitoringTab } from './MonitoringTab'

const prPage: PRBrowserPageApi = {
    github_login: 'alex-dev',
    has_integration: true,
    results: [
        {
            url: 'https://github.com/example/app/pull/5120',
            repository: 'example/app',
            number: 5120,
            title: 'feat(checkout): preload address autocomplete on shipping step',
            state: 'open',
            draft: false,
            author: 'alex-dev',
            created_at: '2026-11-18T11:30:00Z',
            updated_at: '2026-11-18T14:10:00Z',
            report: null,
        },
        {
            url: 'https://github.com/example/app/pull/5114',
            repository: 'example/app',
            number: 5114,
            title: 'fix(uploads): bound image decode concurrency per worker',
            state: 'merged',
            draft: false,
            author: 'alex-dev',
            created_at: '2026-11-16T09:15:00Z',
            updated_at: '2026-11-16T16:45:00Z',
            report: { id: monitoringRows[0].id, status: 'monitoring' },
        },
        {
            url: 'https://github.com/example/app/pull/5108',
            repository: 'example/app',
            number: 5108,
            title: 'fix(exports): stop the nightly export retrying finished files',
            state: 'merged',
            draft: false,
            author: 'alex-dev',
            created_at: '2026-11-14T15:00:00Z',
            updated_at: '2026-11-14T22:20:00Z',
            report: { id: monitoringRows[0].id, status: 'resolved' },
        },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/Monitoring',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: MONITORING_MOCK_NOW,
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [
                    200,
                    { results: monitoringRows, count: monitoringRows.length, next: null, previous: null },
                ],
                '/api/projects/:id/signals/pull_requests': () => [200, prPage],
                '/api/projects/:id/signals/reports/:reportId/checks/': ({ params }) => [
                    200,
                    {
                        results: monitoringChecksForReport(
                            monitoringRows.find((report) => report.id === params.reportId) ?? monitoringRows[0]
                        ),
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': monitoringMetricQueryHandler,
            },
        }),
    ],
}
export default meta
type Story = StoryObj

function WithOpenRows(): JSX.Element {
    const { reports, expandedReportIds } = useValues(monitoringTabLogic)
    const { toggleExpanded } = useActions(monitoringTabLogic)
    useEffect(() => {
        if (!reports || expandedReportIds.length) {
            return
        }
        for (const report of reports) {
            if (/image uploads|one alert per|bounced/.test(report.title ?? '')) {
                toggleExpanded(report.id)
            }
        }
    }, [reports, expandedReportIds.length, toggleExpanded])
    return <MonitoringTab />
}

export const Timeline: Story = {
    render: () => (
        <div className="min-h-screen bg-primary">
            <MonitoringTab />
        </div>
    ),
}

export const TimelineWithOpenRows: Story = {
    render: () => (
        <div className="min-h-screen bg-primary">
            <WithOpenRows />
        </div>
    ),
}

export const TimelineWithPullRequestsPanel: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING, FEATURE_FLAGS.SIGNALS_MONITOR_PR],
    },
    render: () => (
        <div className="flex h-screen flex-col bg-primary">
            <MonitoringTab />
        </div>
    ),
}

export const TimelineAtPhoneWidth: Story = {
    render: () => (
        <div className="min-h-screen bg-primary">
            <div className="mx-auto w-[390px]">
                <WithOpenRows />
            </div>
        </div>
    ),
}
