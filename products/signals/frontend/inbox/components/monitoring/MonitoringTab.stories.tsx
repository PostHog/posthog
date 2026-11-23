import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { MONITORING_MOCK_NOW, monitoringRows } from '../../__mocks__/monitoringMocks'
import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { MonitoringTab } from './MonitoringTab'

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

export const TimelineAtPhoneWidth: Story = {
    render: () => (
        <div className="min-h-screen bg-primary">
            <div className="mx-auto w-[390px]">
                <WithOpenRows />
            </div>
        </div>
    ),
}
