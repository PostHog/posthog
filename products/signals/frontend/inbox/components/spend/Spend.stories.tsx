import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { RecordedSpend } from './RecordedSpend'
import { ReportSpendSection } from './ReportSpendSection'
import { ScoutSpendLabel } from './ScoutSpendLabel'
import { SourceSpendLabel } from './SourceSpendLabel'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Usage',
    parameters: {
        mockDate: '2026-06-11',
        featureFlags: [FEATURE_FLAGS.SELF_DRIVING_USAGE],
        testOptions: { waitForSelector: '[data-attr="report-spend"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/spend/': {
                    period_start: '2026-05-12T00:00:00Z',
                    period_end: '2026-06-11T00:00:00Z',
                    scout_spend: { total_spend: 131.625, incomplete: true },
                    scouts: [
                        { skill_name: 'signals-scout-general', spend: { total_spend: 131.625, incomplete: true } },
                    ],
                },
                '/api/projects/:id/signals/source_spend/': [
                    {
                        source_product: 'error_tracking',
                        source_type: 'issue_created',
                        signal_count: 4,
                        spend: { total_spend: 162.75, incomplete: false },
                    },
                    {
                        source_product: 'github',
                        source_type: 'issue',
                        signal_count: 1,
                        spend: { total_spend: 0.125, incomplete: false },
                    },
                    {
                        source_product: 'linear',
                        source_type: 'issue',
                        signal_count: 1,
                        spend: { total_spend: null, incomplete: true },
                    },
                ],
                '/api/projects/:id/signals/reports/:reportId/spend/': {
                    generation: { total_spend: 162.75, incomplete: false },
                    implementation: { total_spend: 490, incomplete: true },
                    shared_scout_runs: { total_spend: 46.25, incomplete: false },
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj

export const Overview: Story = {
    render: () => (
        <div className="flex max-w-2xl flex-col gap-6 p-4">
            <ReportSpendSection reportId="example-report" />
            <ScoutSpendLabel />
            <div className="flex items-center justify-between gap-2">
                <span>Error tracking</span>
                <SourceSpendLabel sourceProduct="error_tracking" />
            </div>
            <div className="flex items-center justify-between gap-2">
                <span>GitHub</span>
                <SourceSpendLabel sourceProduct="github" />
            </div>
            <div className="flex items-center justify-between gap-2">
                <span>Linear</span>
                <SourceSpendLabel sourceProduct="linear" />
            </div>
            <div className="flex flex-wrap gap-4">
                <RecordedSpend amount={0} />
                <RecordedSpend amount={0.0001} />
            </div>
        </div>
    ),
}
