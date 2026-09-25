import type { Meta, StoryObj } from '@storybook/react'

import { SignalReport, SignalReportStatus } from '../../types'
import { RelevanceShortlist } from './RelevanceShortlist'

const report: SignalReport = {
    id: '01900000-0000-0000-0000-000000000001',
    title: 'Checkout fails when an address has no postal code',
    summary: 'Example report',
    status: SignalReportStatus.READY,
    priority: 'P1',
    actionability: 'immediately_actionable',
    created_at: '2026-09-20T12:00:00Z',
    updated_at: '2026-09-20T12:00:00Z',
    signal_count: 3,
    total_weight: 1,
    artefact_count: 3,
    is_suggested_reviewer: true,
}
const meta: Meta<typeof RelevanceShortlist> = {
    title: 'Products/Signals/Relevance shortlist',
    component: RelevanceShortlist,
    args: {
        reports: [
            report,
            {
                ...report,
                id: '01900000-0000-0000-0000-000000000002',
                title: 'Choose how to handle expired invitations',
                priority: 'P2',
                actionability: 'requires_human_input',
            },
        ],
        loading: false,
        failed: false,
        saving: false,
        lastSnoozed: null,
        onRetry: () => {},
        onShowQueue: () => {},
        onSnooze: () => {},
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const Default: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const Empty: Story = { args: { reports: [] } }
export const Loading: Story = { args: { loading: true } }
export const Error: Story = { args: { failed: true } }
export const Snoozed: Story = { args: { lastSnoozed: report } }
