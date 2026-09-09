import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import {
    reportMetricQueryHandler,
    reportMetricsFixture,
    reportSavedValueMetricFixture,
} from '../../__mocks__/reportMetricMocks'
import { ReportImpactMetrics } from './ReportImpactMetrics'
import { ReportPrimaryMetric } from './ReportPrimaryMetric'

const [primaryMetric, ...supportingMetrics] = reportMetricsFixture

/** The observation in a rail-width column beside the Impact tiles, the way the report detail lays them out. */
function ReportMetricsLayout({ reportId, railWidth }: { reportId: string; railWidth: string }): JSX.Element {
    return (
        <div className="flex flex-wrap items-start gap-6">
            <div className={railWidth}>
                <ReportPrimaryMetric reportId={reportId} metric={primaryMetric} />
            </div>
            <div className="flex min-w-64 flex-1 flex-col gap-3">
                <h2 className="m-0 text-lg font-semibold">Impact</h2>
                <ReportImpactMetrics reportId={reportId} metrics={supportingMetrics} />
            </div>
        </div>
    )
}

const meta: Meta<typeof ReportMetricsLayout> = {
    title: 'Scenes-App/Inbox/Report metrics',
    component: ReportMetricsLayout,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-29',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': reportMetricQueryHandler,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ReportMetricsLayout>

export const Wide: Story = {
    args: { reportId: 'report-with-metrics', railWidth: 'w-[26rem]' },
    render: (args) => (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto max-w-5xl">
                <ReportMetricsLayout {...args} />
            </div>
        </div>
    ),
}

export const Narrow: Story = {
    args: { reportId: 'narrow-report-with-metrics', railWidth: 'w-full' },
    render: (args) => (
        <div className="min-h-screen bg-primary p-6">
            <div className="w-96 max-w-full">
                <ReportMetricsLayout {...args} />
            </div>
        </div>
    ),
}

export const SavedValue: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-6">
            <div className="w-[26rem] max-w-full">
                <ReportPrimaryMetric reportId="report-with-saved-metric" metric={reportSavedValueMetricFixture} />
            </div>
        </div>
    ),
}

export const LiveSupportingMetric: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto max-w-md">
                <ReportImpactMetrics
                    reportId="report-with-live-supporting-metric"
                    metrics={[{ ...primaryMetric, role: 'supporting' }]}
                />
            </div>
        </div>
    ),
}
