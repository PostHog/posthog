import type { Meta, StoryObj } from '@storybook/react'

import { investigationExample } from './investigationExample'
import { InvestigationQueryProposal } from './InvestigationQueryProposal'

const document = investigationExample()
const meta: Meta<typeof InvestigationQueryProposal> = {
    title: 'Scenes-App/Notebooks/Investigations/QueryProposal',
    component: InvestigationQueryProposal,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (Story) => (
            <div className="p-6 max-w-4xl">
                <Story />
            </div>
        ),
    ],
    args: {
        document,
        request: {
            id: 'example-request',
            task: 'compare',
            targetId: document.evidence[0].id,
            originalSql: document.evidence[0].sql,
            prompt: 'Compare conversion by acquisition channel',
        },
        proposal: {
            requestId: 'example-request',
            sql: "SELECT properties.channel AS channel, count() AS signups\nFROM events\nWHERE event = 'signup'\n  AND timestamp >= now() - INTERVAL 30 DAY\nGROUP BY channel\nORDER BY signups DESC\nLIMIT 20",
        },
        onAccept: () => {},
        onDismiss: () => {},
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const Review: Story = {}
export const ConcurrentEdit: Story = {
    args: {
        document: {
            ...document,
            evidence: document.evidence.map((item) => ({ ...item, sql: 'SELECT 42 AS conversion_rate' })),
        },
    },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}
